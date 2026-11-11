"""
statement_completion.py

"Mark statement complete" (2026-11-11): a reviewer can mark a statement
complete on its Exceptions review page, even with exceptions still open,
and un-mark it again. Every mark and un-mark is logged with who and when;
a statement's current state is its newest log row.

A statement counts as Completed on Statement Processing and Exceptions when
it is 100% reconciled (web/statement_processing.py, web/routers/exceptions.py)
OR its newest log row here is "completed". Marking changes nothing else: the
open exceptions stay open and nothing is written to NetSuite.

Storage: statement_completion_log (migrations/029_add_statement_completion_log.sql;
src/lakehouse/azure_sql_migrations.py for Azure SQL). The app has no startup
migration step, so ensure_table() also creates it on first use.
"""

import logging
import threading
from datetime import datetime, timezone

from src.lakehouse.connection import _using_azure_sql
from web import queries

logger = logging.getLogger(__name__)

COMPLETED = "completed"
REOPENED = "reopened"
NOTE_MAX = 500

_SQLITE_DDL = (
    "CREATE TABLE IF NOT EXISTS statement_completion_log ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " statement_id TEXT NOT NULL,"
    " action TEXT NOT NULL,"
    " done_by TEXT NOT NULL,"
    " done_at TEXT NOT NULL,"
    " note TEXT)"
)
_AZURE_DDL = (
    "IF OBJECT_ID('statement_completion_log', 'U') IS NULL "
    "CREATE TABLE statement_completion_log ("
    " id INT IDENTITY(1,1) PRIMARY KEY,"
    " statement_id NVARCHAR(100) NOT NULL,"
    " action NVARCHAR(20) NOT NULL,"
    " done_by NVARCHAR(255) NOT NULL,"
    " done_at NVARCHAR(40) NOT NULL,"
    " note NVARCHAR(500))"
)

_TABLE_READY = {"done": False}
_TABLE_LOCK = threading.Lock()


def ensure_table() -> None:
    """Creates statement_completion_log if it is not there yet (once per process)."""
    if _TABLE_READY["done"]:
        return
    with _TABLE_LOCK:
        if _TABLE_READY["done"]:
            return
        queries.execute_sql(_AZURE_DDL if _using_azure_sql() else _SQLITE_DDL)
        _TABLE_READY["done"] = True


def set_completed(statement_id: str, completed: bool, user: str, note: str = "") -> None:
    """Logs a mark (completed=True) or un-mark by `user`."""
    ensure_table()
    queries.execute_sql(
        "INSERT INTO statement_completion_log (statement_id, action, done_by, done_at, note) VALUES (?, ?, ?, ?, ?)",
        [statement_id, COMPLETED if completed else REOPENED, user,
         datetime.now(timezone.utc).isoformat(), (note or "").strip()[:NOTE_MAX] or None],
    )


def history(statement_id: str) -> list:
    """The statement's log, newest first; [] on any database problem."""
    try:
        ensure_table()
        rows = queries.execute_query(
            "SELECT statement_id, action, done_by, done_at, note FROM statement_completion_log "
            "WHERE statement_id = ? ORDER BY id DESC", [statement_id])
    except Exception as error:
        logger.warning("statement_completion_log read failed for %s: %s", statement_id, error)
        return []
    return rows


def marked(statement_id: str):
    """The newest log row if the statement is marked complete now, else None."""
    rows = history(statement_id)
    return rows[0] if rows and rows[0]["action"] == COMPLETED else None


def all_marked() -> dict:
    """{statement_id: newest row} for every statement marked complete now
    (the list pages); {} on any database problem."""
    try:
        ensure_table()
        rows = queries.execute_query(
            "SELECT statement_id, action, done_by, done_at, note FROM statement_completion_log ORDER BY id")
    except Exception as error:
        logger.warning("statement_completion_log read failed: %s", error)
        return {}
    latest = {}
    for r in rows:  # oldest first, so the newest row per statement wins
        latest[r["statement_id"]] = r
    return {sid: r for sid, r in latest.items() if r["action"] == COMPLETED}


# ---- Follow-up status (2026-11-11) ------------------------------------------
# Separate from Completed: where a statement's follow-up stands -- one of
# STATUSES, or none. A statement can have a status and be Completed. Every
# pick (including clearing it, status '') is logged with who and when; the
# current status is the newest row. Changes nothing else, like Completed.

STATUSES = {
    "requested_copy": "Requested copy from vendor",
    "sent_to_shop": "Sent to shop",
    "waiting_to_post": "Waiting to post",
}

_STATUS_SQLITE_DDL = (
    "CREATE TABLE IF NOT EXISTS statement_status_log ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " statement_id TEXT NOT NULL,"
    " status TEXT NOT NULL,"
    " set_by TEXT NOT NULL,"
    " set_at TEXT NOT NULL)"
)
_STATUS_AZURE_DDL = (
    "IF OBJECT_ID('statement_status_log', 'U') IS NULL "
    "CREATE TABLE statement_status_log ("
    " id INT IDENTITY(1,1) PRIMARY KEY,"
    " statement_id NVARCHAR(100) NOT NULL,"
    " status NVARCHAR(40) NOT NULL,"
    " set_by NVARCHAR(255) NOT NULL,"
    " set_at NVARCHAR(40) NOT NULL)"
)
_STATUS_TABLE_READY = {"done": False}


def ensure_status_table() -> None:
    """Creates statement_status_log if it is not there yet (once per process)."""
    if _STATUS_TABLE_READY["done"]:
        return
    with _TABLE_LOCK:
        if _STATUS_TABLE_READY["done"]:
            return
        queries.execute_sql(_STATUS_AZURE_DDL if _using_azure_sql() else _STATUS_SQLITE_DDL)
        _STATUS_TABLE_READY["done"] = True


def set_status(statement_id: str, status: str, user: str) -> None:
    """Logs `status` (a STATUSES key, or '' to clear it) for the statement."""
    if status and status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    ensure_status_table()
    queries.execute_sql(
        "INSERT INTO statement_status_log (statement_id, status, set_by, set_at) VALUES (?, ?, ?, ?)",
        [statement_id, status or "", user, datetime.now(timezone.utc).isoformat()],
    )


def _with_label(row: dict) -> dict:
    return {**row, "label": STATUSES.get(row["status"], row["status"])}


def current_status(statement_id: str):
    """The newest row (with "label") if the statement has a status now, else None."""
    try:
        ensure_status_table()
        rows = queries.execute_query(
            "SELECT statement_id, status, set_by, set_at FROM statement_status_log "
            "WHERE statement_id = ? ORDER BY id DESC", [statement_id])
    except Exception as error:
        logger.warning("statement_status_log read failed for %s: %s", statement_id, error)
        return None
    return _with_label(rows[0]) if rows and rows[0]["status"] else None


def all_statuses() -> dict:
    """{statement_id: newest row with "label"} for every statement with a
    status now (the Exceptions list); {} on any database problem."""
    try:
        ensure_status_table()
        rows = queries.execute_query(
            "SELECT statement_id, status, set_by, set_at FROM statement_status_log ORDER BY id")
    except Exception as error:
        logger.warning("statement_status_log read failed: %s", error)
        return {}
    latest = {}
    for r in rows:
        latest[r["statement_id"]] = r
    return {sid: _with_label(r) for sid, r in latest.items() if r["status"]}
