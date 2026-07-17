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
    return execute_query(
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


def get_open_exceptions_count() -> int:
    rows = execute_query("SELECT COUNT(*) AS c FROM gold_exceptions WHERE exception_status = 'OPEN'")
    return rows[0]["c"] or 0 if rows else 0


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
# Reports
# ---------------------------------------------------------------------------

def get_all_runs() -> list:
    return execute_query(
        """
        SELECT statement_id, vendor_name, statement_period, total_invoice_count,
               matched_count, exception_count, statement_total, overall_status,
               reconciliation_timestamp
        FROM gold_reconciliation_summary
        ORDER BY reconciliation_timestamp DESC
        """
    )


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
