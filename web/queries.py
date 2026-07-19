"""
queries.py

All Azure SQL access for the web app, layered on top of
src.lakehouse.connection (the same execute_sql/execute_query helpers the
pipeline itself uses — see that module's docstring for the SQLite/Azure
SQL abstraction). Routers stay thin; this module owns the SQL.
"""

import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.lakehouse.connection import execute_query, execute_sql

REASON_LABELS = {
    "Invoice Missing": "missing",
    "Amount Mismatch": "amount mismatch",
    "EXTRACTION_INCOMPLETE": "extraction incomplete",
}


# ---------------------------------------------------------------------------
# Home / dashboard
# ---------------------------------------------------------------------------

# One row per vendor — their single latest run — via a GROUP BY subquery
# joined back for the full row, rather than LIMIT-1-per-vendor tricks that
# don't translate cleanly across the SQLite/Azure SQL backends. Every run
# now has a vendor_name (the intake pipeline falls back to a filename-
# derived name when extraction can't determine one — see
# notebooks/01_document_intake.py), so there's no null-vendor case to
# exclude here anymore.
_LATEST_RUN_PER_VENDOR = """
    SELECT vendor_name, MAX(reconciliation_timestamp) AS max_ts
    FROM gold_reconciliation_summary
    GROUP BY vendor_name
"""


def get_kpis() -> dict:
    totals = execute_query(
        f"""
        SELECT
            COALESCE(SUM(s.total_invoice_count), 0) AS total_invoices,
            COALESCE(SUM(s.matched_count), 0) AS auto_reconciled,
            COALESCE(SUM(s.statement_total), 0) AS statement_total,
            COUNT(DISTINCT s.vendor_name) AS vendor_count
        FROM gold_reconciliation_summary s
        INNER JOIN ({_LATEST_RUN_PER_VENDOR}) latest
            ON s.vendor_name = latest.vendor_name
            AND s.reconciliation_timestamp = latest.max_ts
        """
    )[0]
    open_exceptions = get_open_exceptions_count()
    total_invoices = totals["total_invoices"] or 0
    auto_reconciled = totals["auto_reconciled"] or 0
    return {
        "total_invoices": total_invoices,
        "auto_reconciled": auto_reconciled,
        "open_exceptions": open_exceptions,
        "statement_total": totals["statement_total"] or 0,
        "vendor_count": totals["vendor_count"] or 0,
        "match_rate": round((auto_reconciled / total_invoices) * 100, 1) if total_invoices else 0.0,
    }


def get_recent_runs(limit: int = 10) -> list:
    # The pipeline's SQLite->Azure SQL translator (see src/lakehouse/connection.py)
    # only rewrites a trailing "LIMIT <digit>" literal, not a bound "LIMIT ?"
    # placeholder — so the row cap is inlined as a validated int, not a param.
    limit = int(limit)
    rows = execute_query(
        f"""
        SELECT s.statement_id, s.vendor_name, s.statement_period, s.total_invoice_count,
               s.matched_count, s.exception_count, s.overall_status, s.reconciliation_timestamp
        FROM gold_reconciliation_summary s
        INNER JOIN ({_LATEST_RUN_PER_VENDOR}) latest
            ON s.vendor_name = latest.vendor_name
            AND s.reconciliation_timestamp = latest.max_ts
        ORDER BY s.reconciliation_timestamp DESC
        LIMIT {limit}
        """
    )
    return _with_live_exception_counts(rows)


def get_open_exceptions_count() -> int:
    rows = execute_query("SELECT COUNT(*) AS c FROM gold_exceptions WHERE exception_status = 'OPEN'")
    return rows[0]["c"] or 0 if rows else 0


def _live_open_exception_count(statement_id: str) -> int:
    """
    Live count of OPEN gold_exceptions rows for a statement — the same
    live query the detail page already uses (get_open_exceptions() /
    get_exception_counts()). Used to replace gold_reconciliation_summary's
    cached exception_count/overall_status, which go stale for two reasons:

      1. EXTRACTION_INCOMPLETE rows are raised by intake (see
         notebooks/01_document_intake.py write_skip_exception()) AFTER
         matching's Silver-based classification already ran, so matching
         (src/matching/engine.py) never counts them into the summary it
         writes.
      2. Resolving an exception (Accept/Dispute/Write-off) updates
         gold_exceptions.exception_status but never touches the summary's
         cached count.
    """
    rows = execute_query(
        "SELECT COUNT(*) AS c FROM gold_exceptions WHERE statement_id = ? AND exception_status = 'OPEN'",
        [statement_id],
    )
    return rows[0]["c"] or 0 if rows else 0


def _with_live_exception_counts(rows: list) -> list:
    """Overwrites exception_count/overall_status on each row (as returned
    by a gold_reconciliation_summary query) with a live count — see
    _live_open_exception_count(). overall_status only ever needs to
    distinguish RECONCILED from not here — every consumer template
    (home.html, reports.html) renders any non-RECONCILED value identically
    as a generic "Exceptions" badge."""
    for row in rows:
        count = _live_open_exception_count(row["statement_id"])
        row["exception_count"] = count
        row["overall_status"] = "RECONCILED" if count == 0 else "EXCEPTIONS_PRESENT"
    return rows


# ---------------------------------------------------------------------------
# Exceptions — vendors overview
# ---------------------------------------------------------------------------

def get_vendor_summaries() -> list:
    """One row per vendor: their most recent reconciliation run, plus a
    breakdown of open-exception reasons for that run's footer note."""
    rows = execute_query(
        """
        SELECT statement_id, vendor_name, statement_period, total_invoice_count,
               matched_count, exception_count, statement_total, overall_status,
               reconciliation_timestamp
        FROM gold_reconciliation_summary
        ORDER BY reconciliation_timestamp ASC
        """
    )
    latest_by_vendor = {}
    for row in rows:
        latest_by_vendor[row["vendor_name"]] = row  # later (ASC) rows win
    vendors = sorted(latest_by_vendor.values(), key=lambda v: v["vendor_name"] or "")

    for vendor in vendors:
        reason_rows = execute_query(
            """
            SELECT exception_reason, COUNT(*) AS c
            FROM gold_exceptions
            WHERE statement_id = ? AND exception_status = 'OPEN'
            GROUP BY exception_reason
            """,
            [vendor["statement_id"]],
        )
        vendor["reason_breakdown"] = {
            REASON_LABELS.get(r["exception_reason"], r["exception_reason"]): r["c"]
            for r in reason_rows
        }
        # Live count (sum of the OPEN breakdown just fetched above) —
        # replaces the stale exception_count from gold_reconciliation_summary,
        # which matching writes once from Silver-classified exceptions only
        # and never updates again. See _live_open_exception_count().
        vendor["exception_count"] = sum(r["c"] for r in reason_rows)
    return vendors


# ---------------------------------------------------------------------------
# Exceptions — review (per vendor)
# ---------------------------------------------------------------------------

def get_vendor_latest_statement(vendor_name: str):
    rows = execute_query(
        """
        SELECT statement_id, vendor_name, statement_period, total_invoice_count,
               matched_count, exception_count, statement_total, overall_status
        FROM gold_reconciliation_summary
        WHERE vendor_name = ?
        ORDER BY reconciliation_timestamp DESC
        LIMIT 1
        """,
        [vendor_name],
    )
    return rows[0] if rows else None


_REASON_FILTER_SQL = {
    "missing": "Invoice Missing",
    "mismatch": "Amount Mismatch",
}


_OPEN_EXCEPTIONS_SELECT = """
    SELECT ge.*, s.invoice_date AS invoice_date
    FROM gold_exceptions ge
    LEFT JOIN silver_reconciliation_standard s ON ge.statement_record_id = s.record_id
"""


def get_open_exceptions(statement_id: str, reason_filter: str = None) -> list:
    reason = _REASON_FILTER_SQL.get(reason_filter)
    if reason:
        return execute_query(
            _OPEN_EXCEPTIONS_SELECT + """
            WHERE ge.statement_id = ? AND ge.exception_status = 'OPEN' AND ge.exception_reason = ?
            ORDER BY ge.invoice_number
            """,
            [statement_id, reason],
        )
    return execute_query(
        _OPEN_EXCEPTIONS_SELECT + """
        WHERE ge.statement_id = ? AND ge.exception_status = 'OPEN'
        ORDER BY ge.invoice_number
        """,
        [statement_id],
    )


def get_exception_counts(statement_id: str):
    total = execute_query(
        "SELECT COUNT(*) AS c FROM gold_exceptions WHERE statement_id = ?", [statement_id]
    )[0]["c"] or 0
    resolved = execute_query(
        "SELECT COUNT(*) AS c FROM gold_exceptions WHERE statement_id = ? AND exception_status != 'OPEN'",
        [statement_id],
    )[0]["c"] or 0
    return total, resolved


def resolve_exception(exception_id: str, statement_id: str, vendor_name: str,
                       invoice_number: str, reason_code: str, disposition_status: str,
                       notes: str, disposed_by: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    execute_sql(
        """
        INSERT INTO exception_dispositions (
            exception_id, statement_id, vendor_name, invoice_number, reason_code,
            disposition_status, disposition_notes, disposed_by, disposed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [exception_id, statement_id, vendor_name, invoice_number, reason_code,
         disposition_status, notes, disposed_by, now],
    )
    execute_sql(
        "UPDATE gold_exceptions SET exception_status = 'RESOLVED', date_resolved = ? WHERE exception_id = ?",
        [now, exception_id],
    )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def get_vendor_name_for_statement(statement_id: str):
    rows = execute_query(
        "SELECT vendor_name FROM document_intake_log WHERE statement_id = ? LIMIT 1",
        [statement_id],
    )
    if rows and rows[0]["vendor_name"]:
        return rows[0]["vendor_name"]
    # Falls back to gold_reconciliation_summary: on a cache hit, the
    # pipeline's run_intake() re-normalizes Bronze->Silver under a new
    # statement_id but never calls write_intake_log() again (see
    # notebooks/01_document_intake.py), so document_intake_log has no row
    # for that statement_id even though the matching engine already wrote
    # the vendor to gold_reconciliation_summary from the Silver rows.
    rows = execute_query(
        "SELECT vendor_name FROM gold_reconciliation_summary WHERE statement_id = ? LIMIT 1",
        [statement_id],
    )
    return rows[0]["vendor_name"] if rows else None


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_user_by_email(email: str):
    if not email:
        return None
    rows = execute_query(
        """
        SELECT id, name, email, password_hash, is_active, created_at, created_by
        FROM users WHERE email = ?
        """,
        [email.strip().lower()],
    )
    return rows[0] if rows else None


def list_users() -> list:
    return execute_query(
        "SELECT id, name, email, is_active, created_at, created_by FROM users ORDER BY created_at"
    )


def create_user(name: str, email: str, password_hash: str, created_by: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    execute_sql(
        """
        INSERT INTO users (name, email, password_hash, is_active, created_at, created_by)
        VALUES (?, ?, ?, 1, ?, ?)
        """,
        [name, email.strip().lower(), password_hash, now, created_by],
    )


def delete_user_by_email(email: str) -> None:
    execute_sql("DELETE FROM users WHERE email = ?", [email.strip().lower()])


# ---------------------------------------------------------------------------
# Jobs (background reconciliation queue — see web/worker.py)
# ---------------------------------------------------------------------------

def create_job(job_id: str, pdf_filename: str, pdf_path: str, submitted_by: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    execute_sql(
        """
        INSERT INTO jobs (job_id, pdf_filename, pdf_path, status, submitted_by, submitted_at)
        VALUES (?, ?, ?, 'PENDING', ?, ?)
        """,
        [job_id, pdf_filename, pdf_path, submitted_by, now],
    )


def get_next_pending_job():
    rows = execute_query(
        "SELECT * FROM jobs WHERE status = 'PENDING' ORDER BY submitted_at LIMIT 1"
    )
    return rows[0] if rows else None


def update_job_status(job_id: str, status: str, started_at: str = None,
                       completed_at: str = None, statement_id: str = None,
                       vendor_name: str = None, error_message: str = None) -> None:
    """Builds the SET clause from whichever fields are relevant to this
    transition — PENDING->PROCESSING only sets started_at; COMPLETED/FAILED
    also set completed_at plus their own outcome fields."""
    sets = ["status = ?"]
    params = [status]
    if started_at is not None:
        sets.append("started_at = ?")
        params.append(started_at)
    if completed_at is not None:
        sets.append("completed_at = ?")
        params.append(completed_at)
    if statement_id is not None:
        sets.append("statement_id = ?")
        params.append(statement_id)
    if vendor_name is not None:
        sets.append("vendor_name = ?")
        params.append(vendor_name)
    if error_message is not None:
        sets.append("error_message = ?")
        params.append(error_message)
    params.append(job_id)
    execute_sql(f"UPDATE jobs SET {', '.join(sets)} WHERE job_id = ?", params)


def get_active_jobs() -> list:
    """Jobs still relevant to surface on the dashboard: not yet finished
    (PENDING/PROCESSING), or finished with an error nobody's addressed yet
    (FAILED). COMPLETED jobs drop out of this list — their result is
    already visible as a normal reconciliation run."""
    return execute_query(
        """
        SELECT * FROM jobs
        WHERE status IN ('PENDING', 'PROCESSING', 'FAILED')
        ORDER BY submitted_at DESC
        """
    )


def get_job_history() -> list:
    return execute_query("SELECT * FROM jobs ORDER BY submitted_at DESC")


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def get_all_runs() -> list:
    rows = execute_query(
        """
        SELECT statement_id, vendor_name, statement_period, total_invoice_count,
               matched_count, exception_count, statement_total, overall_status,
               reconciliation_timestamp
        FROM gold_reconciliation_summary
        ORDER BY reconciliation_timestamp DESC
        """
    )
    return _with_live_exception_counts(rows)


def get_statement_report(statement_id: str) -> dict:
    summary_rows = execute_query(
        "SELECT * FROM gold_reconciliation_summary WHERE statement_id = ? LIMIT 1",
        [statement_id],
    )
    summary = summary_rows[0] if summary_rows else None

    intake_rows = execute_query(
        "SELECT * FROM document_intake_log WHERE statement_id = ? LIMIT 1",
        [statement_id],
    )
    intake = intake_rows[0] if intake_rows else None

    matched = execute_query(
        """
        SELECT invoice_number, ro_number, statement_amount, erp_amount, match_level
        FROM gold_matched_invoices
        WHERE statement_id = ?
        ORDER BY invoice_number
        """,
        [statement_id],
    )

    exceptions = execute_query(
        """
        SELECT * FROM gold_exceptions
        WHERE statement_id = ?
        ORDER BY exception_status, exception_reason, invoice_number
        """,
        [statement_id],
    )

    return {
        "summary": summary,
        "intake": intake,
        "matched": matched,
        "exceptions": exceptions,
    }
