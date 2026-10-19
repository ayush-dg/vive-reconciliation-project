"""Saves NetSuite write-back runs to the application database.

Two tables (migrations/021_add_netsuite_writeback_log.sql, and the matching
definitions in src/lakehouse/azure_sql_migrations.py):

  netsuite_writeback_run     one row per run for a statement
  netsuite_writeback_record  one row per invoice line of that run

It goes through src/lakehouse/connection.py like the jobs table does, so it is
Azure SQL in the deployed app and SQLite locally, with no code of its own for
either.

EVERYTHING HERE IS BEST-EFFORT. The write-back has already happened (and its
JSON log is already written) by the time this runs, so a database problem
must never fail a job or hide the real result: every public function that
writes catches its own errors, logs a warning and returns None.
"""
import json
import logging
import uuid
from datetime import datetime, timezone

from src.lakehouse.connection import _run_with_retry, execute_query
from src.netsuite.writeback import (
    CAT_HELD_BY_OTHER,
    CAT_LINK_ONLY_FAILED,
    CAT_NOT_ATTEMPTED,
    CAT_PERIOD_LOCKED,
    PATCH_LINK_ONLY,
    WRITE_ACTIONS,
    failure_counts,
    skip_category,
    skip_counts,
    unattempted_plans,
)

logger = logging.getLogger(__name__)

OUTCOME_WRITTEN = "written"
OUTCOME_NOT_WRITTEN = "not written"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_REVERTED = "reverted"          # an undo run (see save_revert)
OUTCOME_NOT_ATTEMPTED = "not attempted"
OUTCOME_REVERTED = "reverted"

_RUN_COLUMNS = (
    "run_id", "statement_id", "job_id", "source", "sandbox", "outcome", "started_at", "finished_at",
    "written", "failed", "period_locked", "held_by_other", "not_written", "not_written_counts",
    "error_type", "error_message", "error_traceback", "log_path",
)
_RECORD_COLUMNS = (
    "run_id", "statement_id", "invoice_number", "statement_amount", "action", "outcome", "reason",
    "record_type", "record_id", "detail", "seconds", "fields_sent", "previous_values",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value) -> str:
    return json.dumps(value, default=str)


def _insert_sql(table: str, columns: tuple) -> str:
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})"


def _insert_many(table: str, columns: tuple, rows: list) -> None:
    """Inserts all rows in one transaction on one connection. Goes through
    connection._run_with_retry so a dropped Azure SQL connection is retried
    with a fresh one, like execute_sql() does."""
    if not rows:
        return

    def _run(conn):
        cursor = conn.cursor()
        cursor.executemany(_insert_sql(table, columns), rows)
        conn.commit()

    _run_with_retry(_run)


def _amount(plan):
    return None if plan.statement_amount is None else float(plan.statement_amount)


def _result_row(run_id: str, statement_id: str, result) -> tuple:
    plan = result.plan
    outcome = OUTCOME_WRITTEN if result.ok else (result.category or "failed")
    return (
        run_id, statement_id, plan.invoice_number, _amount(plan), plan.action, outcome,
        "" if result.ok else (result.category or "failed"),
        plan.record_type, result.new_record_id or plan.record_id, result.detail, result.seconds,
        _json(plan.fields), _json(plan.previous),
    )


def _not_written_row(run_id: str, statement_id: str, plan) -> tuple:
    return (
        run_id, statement_id, plan.invoice_number, _amount(plan), plan.action, OUTCOME_NOT_WRITTEN,
        skip_category(plan), plan.record_type, plan.record_id, plan.note, None,
        _json(plan.fields), _json(plan.previous),
    )


def _unattempted_row(run_id: str, statement_id: str, plan) -> tuple:
    return (
        run_id, statement_id, plan.invoice_number, _amount(plan), plan.action, OUTCOME_NOT_ATTEMPTED,
        CAT_NOT_ATTEMPTED, plan.record_type, plan.record_id, "the run stopped before this write was attempted",
        None, _json(plan.fields), _json(plan.previous),
    )


def _record_rows(run_id: str, statement_id: str, results: list, plans: list) -> list:
    rows = [_result_row(run_id, statement_id, r) for r in results]
    rows += [_not_written_row(run_id, statement_id, p) for p in plans if p.action not in WRITE_ACTIONS]
    rows += [_unattempted_row(run_id, statement_id, p) for p in unattempted_plans(plans, results)]
    return rows


def _run_counts(results: list, plans: list) -> dict:
    failures = failure_counts(results)
    locked = failures.pop(CAT_PERIOD_LOCKED, 0)
    held = failures.pop(CAT_HELD_BY_OTHER, 0)
    link_failed = failures.pop(CAT_LINK_ONLY_FAILED, 0)   # a missing link is not a failed result
    not_written = skip_counts(plans, results)
    if link_failed:
        not_written[CAT_LINK_ONLY_FAILED] = link_failed
    return {
        "written": sum(1 for r in results if r.ok and r.plan.action != PATCH_LINK_ONLY),
        "failed": sum(failures.values()),
        "period_locked": locked,
        "held_by_other": held,
        "not_written": sum(not_written.values()),
        "not_written_counts": _json(not_written),
    }


def save_run(statement_id: str, results: list, plans: list, *, started_at: str, source: str = "pipeline",
             sandbox: str = None, log_path: str = None, job_id: str = None):
    """Saves one finished run and its per-invoice rows. Returns the run_id,
    or None if the database could not be written (never raises)."""
    try:
        run_id = str(uuid.uuid4())
        counts = _run_counts(results, plans)
        run_row = (
            run_id, statement_id, job_id, source, sandbox, RUN_COMPLETED, started_at, now_iso(),
            counts["written"], counts["failed"], counts["period_locked"], counts["held_by_other"],
            counts["not_written"], counts["not_written_counts"], None, None, None, log_path,
        )
        _insert_many("netsuite_writeback_run", _RUN_COLUMNS, [run_row])
        _insert_many("netsuite_writeback_record", _RECORD_COLUMNS,
                     _record_rows(run_id, statement_id, results, plans))
        return run_id
    except Exception:  # best-effort: see the module docstring
        logger.warning("Could not save the NetSuite write-back run for %s to the database",
                       statement_id, exc_info=True)
        return None


def save_failed_run(statement_id: str, exc: Exception, *, started_at: str, source: str = "pipeline",
                    log_path: str = None, job_id: str = None):
    """Saves a run that failed as a whole (planning or connection error).
    Returns the run_id, or None if the database could not be written."""
    import traceback
    try:
        run_id = str(uuid.uuid4())
        run_row = (
            run_id, statement_id, job_id, source, None, RUN_FAILED, started_at, now_iso(),
            0, 0, 0, 0, 0, _json({}), type(exc).__name__, str(exc),
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), log_path,
        )
        _insert_many("netsuite_writeback_run", _RUN_COLUMNS, [run_row])
        return run_id
    except Exception:  # best-effort: see the module docstring
        logger.warning("Could not save the failed NetSuite write-back run for %s to the database",
                       statement_id, exc_info=True)
        return None


def save_revert(statement_id: str, results: list, *, started_at: str, source: str = "cli",
                sandbox: str = None, log_path: str = None, job_id: str = None):
    """Saves an undo run: which records were reset or deleted. `results` are
    (action, ok, detail) tuples from writeback.apply_revert(). It becomes the
    statement's newest run, so the app stops showing "written" for a statement
    whose NetSuite records have since been cleared. Returns the run_id, or None
    if the database could not be written (never raises)."""
    try:
        run_id = str(uuid.uuid4())
        reverted = sum(1 for _, ok, _ in results if ok)
        run_row = (
            run_id, statement_id, job_id, source, sandbox, RUN_REVERTED, started_at, now_iso(),
            0, len(results) - reverted, 0, 0, 0, _json({"reverted": reverted}), None, None, None, log_path,
        )
        records = [
            (run_id, statement_id, action["invoice_number"], None, f"REVERT_{action['op']}",
             OUTCOME_REVERTED if ok else "failed", "" if ok else "failed", action["record_type"],
             action["record_id"], detail, None, _json(action.get("body") or {}), _json({}))
            for action, ok, detail in results
        ]
        _insert_many("netsuite_writeback_run", _RUN_COLUMNS, [run_row])
        _insert_many("netsuite_writeback_record", _RECORD_COLUMNS, records)
        return run_id
    except Exception:  # best-effort: see the module docstring
        logger.warning("Could not save the NetSuite revert run for %s to the database",
                       statement_id, exc_info=True)
        return None


def get_runs(statement_id: str) -> list:
    """Every saved run for a statement, newest first."""
    return execute_query(
        "SELECT * FROM netsuite_writeback_run WHERE statement_id = ? ORDER BY started_at DESC, id DESC",
        [statement_id])


def get_latest_runs(statement_ids) -> dict:
    """{statement_id: its newest run} for many statements in one go (a page of
    cards), instead of one query per statement. Statements with no saved run
    are simply absent."""
    ids = [s for s in dict.fromkeys(statement_ids) if s]
    latest = {}
    for start in range(0, len(ids), 200):
        chunk = ids[start:start + 200]
        rows = execute_query(
            "SELECT * FROM netsuite_writeback_run WHERE statement_id IN "
            f"({','.join('?' * len(chunk))}) ORDER BY started_at DESC, id DESC", chunk)
        for row in rows:
            latest.setdefault(row["statement_id"], row)
    return latest


def get_records(run_id: str) -> list:
    """The per-invoice rows of one run."""
    return execute_query(
        "SELECT * FROM netsuite_writeback_record WHERE run_id = ? ORDER BY id", [run_id])
