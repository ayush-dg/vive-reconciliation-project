"""
queries.py

All Azure SQL access for the web app, layered on top of
src.lakehouse.connection (the same execute_sql/execute_query helpers the
pipeline itself uses — see that module's docstring for the SQLite/Azure
SQL abstraction). Routers stay thin; this module owns the SQL.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.lakehouse.connection import execute_query, execute_sql
from src.matching.engine import score_exception_confidence, score_overall_status
from src.shop_owners import get_shop_owner

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
        "pending_review_count": get_pending_review_count(),
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
    """
    Live count of OPEN gold_exceptions rows, scoped to each vendor's LATEST
    statement_id only (same _LATEST_RUN_PER_VENDOR scoping get_kpis()/
    get_recent_runs() already use) — a flat, unscoped COUNT(*) here would
    also pick up exceptions still OPEN on a superseded run of the same
    vendor/period (e.g. a statement re-run several times while debugging a
    cache/connectivity issue, producing multiple statement_ids), which the
    recent-runs table correctly excludes. Without this scoping, this KPI
    and the table's per-row exception_count (see _with_live_exception_counts())
    disagree — the whole point of both is to describe the same "open
    exceptions right now" state.
    """
    rows = execute_query(
        f"""
        SELECT COUNT(*) AS c
        FROM gold_exceptions ge
        INNER JOIN gold_reconciliation_summary s ON ge.statement_id = s.statement_id
        INNER JOIN ({_LATEST_RUN_PER_VENDOR}) latest
            ON s.vendor_name = latest.vendor_name
            AND s.reconciliation_timestamp = latest.max_ts
        WHERE ge.exception_status = 'OPEN'
        """
    )
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
    breakdown of open-exception reasons for that run's footer note.

    Also includes "exceptions-only" vendors: ones with OPEN gold_exceptions
    rows raised against a statement_id that never got a
    gold_reconciliation_summary row at all -- e.g. a review-queue row
    flagged via action_review_item() before that vendor's PDF finished a
    full pipeline run (see web/routers/review_queue.py). Without this,
    such a vendor's exceptions are real and OPEN but never show up on the
    exceptions page — the vendor cards only ever queried
    gold_reconciliation_summary. See _get_exceptions_only_vendors()."""
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
    vendors = list(latest_by_vendor.values())

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

    vendors.extend(_get_exceptions_only_vendors())
    return sorted(vendors, key=lambda v: v["vendor_name"] or "")


def _get_exceptions_only_vendors() -> list:
    """Synthesizes a vendor-card-shaped row for each source_file with OPEN
    gold_exceptions raised against a statement_id that has no
    gold_reconciliation_summary row at all. These rows have no Bronze/
    Silver data behind them (no pipeline run ever completed for that
    statement_id), so there's no invoice total, matched count, or
    statement value to show — only the exception itself.

    gold_exceptions has no vendor_name column (flagged review-queue rows
    don't set vendor_id either — see action_review_item()), so source_file
    stands in as the grouping key, the same way review_queue.py groups by
    source_file. Note: if this same vendor separately already has a normal
    summary-backed card under a differently-derived vendor_name, it'll
    show up as a second, duplicate-looking card here — there's no reliable
    way to link the two without a real vendor identity on gold_exceptions.
    """
    orphan_rows = execute_query(
        """
        SELECT ge.source_file, ge.exception_reason, COUNT(*) AS c
        FROM gold_exceptions ge
        WHERE ge.exception_status = 'OPEN'
          AND NOT EXISTS (
              SELECT 1 FROM gold_reconciliation_summary s
              WHERE s.statement_id = ge.statement_id
          )
        GROUP BY ge.source_file, ge.exception_reason
        """
    )
    by_source_file = {}
    for row in orphan_rows:
        source_file = row["source_file"] or "Unknown source"
        by_source_file.setdefault(source_file, {})[row["exception_reason"]] = row["c"]

    vendors = []
    for source_file, reason_counts in by_source_file.items():
        vendors.append({
            "statement_id": None,
            "vendor_name": _vendor_name_from_source_file(source_file),
            "statement_period": None,
            "total_invoice_count": 0,
            "matched_count": 0,
            "exception_count": sum(reason_counts.values()),
            "statement_total": 0,
            "overall_status": "EXCEPTIONS_PRESENT",
            "reconciliation_timestamp": None,
            "reason_breakdown": {
                REASON_LABELS.get(reason, reason): c
                for reason, c in reason_counts.items()
            },
            "exceptions_only": True,
        })
    return vendors


def _vendor_name_from_source_file(source_file: str) -> str:
    """Best-effort display name for a vendor with no summary row (and thus
    no AI-extracted vendor_name) — the same fallback title-casing
    notebooks/01_document_intake.py's derive_vendor_name_from_filename()
    uses when extraction itself can't determine a vendor_name."""
    stem = os.path.splitext(source_file)[0]
    return stem.replace("_", " ").replace("-", " ").title()


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


def get_exceptions_only_vendor(vendor_name: str):
    """Statement-shaped lookup for an "exceptions-only" vendor (see
    _get_exceptions_only_vendors()) -- used by the exceptions detail route
    when get_vendor_latest_statement() finds nothing, so a vendor raised
    straight to gold_exceptions (e.g. a flagged review-queue row, before
    its PDF got a full pipeline run) is still reachable instead of hitting
    "No reconciliation run found".

    Re-derives every orphaned source_file's display name (the same
    derivation _get_exceptions_only_vendors() used to build the vendor
    card link) and matches it against vendor_name, since gold_exceptions
    has no vendor_name column to look up directly. Returns None if
    vendor_name doesn't match any orphaned source_file."""
    orphan_source_files = execute_query(
        """
        SELECT DISTINCT ge.source_file
        FROM gold_exceptions ge
        WHERE ge.exception_status = 'OPEN'
          AND NOT EXISTS (
              SELECT 1 FROM gold_reconciliation_summary s
              WHERE s.statement_id = ge.statement_id
          )
        """
    )
    source_file = next(
        (r["source_file"] for r in orphan_source_files
         if _vendor_name_from_source_file(r["source_file"] or "Unknown source") == vendor_name),
        None,
    )
    if not source_file:
        return None

    count_rows = execute_query(
        """
        SELECT COUNT(*) AS c
        FROM gold_exceptions ge
        WHERE ge.source_file = ? AND ge.exception_status = 'OPEN'
          AND NOT EXISTS (
              SELECT 1 FROM gold_reconciliation_summary s
              WHERE s.statement_id = ge.statement_id
          )
        """,
        [source_file],
    )
    return {
        "statement_id": None,
        "vendor_name": vendor_name,
        "source_file": source_file,
        "statement_period": None,
        "total_invoice_count": 0,
        "matched_count": 0,
        "exception_count": count_rows[0]["c"] or 0 if count_rows else 0,
        "statement_total": 0,
        "overall_status": "EXCEPTIONS_PRESENT",
        "exceptions_only": True,
    }


_REASON_FILTER_SQL = {
    "missing": "Invoice Missing",
    "mismatch": "Amount Mismatch",
}


_OPEN_EXCEPTIONS_SELECT = """
    SELECT ge.*, s.invoice_date AS invoice_date
    FROM gold_exceptions ge
    LEFT JOIN silver_reconciliation_standard s ON ge.statement_record_id = s.record_id
"""


def _parse_datetime(value):
    """Normalizes a timestamp column value into a datetime, or None if
    value is falsy. Every timestamp column in this schema is written as
    an ISO8601 string (via datetime.now(timezone.utc).isoformat()), but
    Azure SQL's pyodbc driver returns DATETIME2 columns (e.g.
    gold_exceptions.escalated_at) as native Python datetime objects
    already, not strings -- unlike every other timestamp column here,
    which is NVARCHAR/TEXT on both backends and always comes back as a
    plain string. Accepting either means every caller below can stay
    agnostic to which case it's in."""
    if not value:
        return None
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def _days_since(iso_timestamp):
    """Whole days between iso_timestamp (see _parse_datetime() for the
    accepted shapes) and now, or None if iso_timestamp is falsy."""
    dt = _parse_datetime(iso_timestamp)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).days


def _with_aging_fields(rows: list) -> list:
    """Attaches days_open (from date_raised) and, for already-escalated
    rows, days_since_escalated (from escalated_at) to every exception row
    -- see exceptions_review.html's aging/escalation display."""
    for row in rows:
        row["days_open"] = _days_since(row.get("date_raised"))
        row["days_since_escalated"] = (
            _days_since(row.get("escalated_at")) if row.get("escalation_status") == "ESCALATED" else None
        )
    return rows


def get_open_exceptions(statement_id: str, reason_filter: str = None) -> list:
    reason = _REASON_FILTER_SQL.get(reason_filter)
    if reason:
        return _with_aging_fields(execute_query(
            _OPEN_EXCEPTIONS_SELECT + """
            WHERE ge.statement_id = ? AND ge.exception_status = 'OPEN' AND ge.exception_reason = ?
            ORDER BY ge.invoice_number
            """,
            [statement_id, reason],
        ))
    return _with_aging_fields(execute_query(
        _OPEN_EXCEPTIONS_SELECT + """
        WHERE ge.statement_id = ? AND ge.exception_status = 'OPEN'
        ORDER BY ge.invoice_number
        """,
        [statement_id],
    ))


def get_exception_counts(statement_id: str):
    total = execute_query(
        "SELECT COUNT(*) AS c FROM gold_exceptions WHERE statement_id = ?", [statement_id]
    )[0]["c"] or 0
    resolved = execute_query(
        "SELECT COUNT(*) AS c FROM gold_exceptions WHERE statement_id = ? AND exception_status != 'OPEN'",
        [statement_id],
    )[0]["c"] or 0
    return total, resolved


# ---------------------------------------------------------------------------
# Exceptions — review, "exceptions-only" vendors (no summary row)
# ---------------------------------------------------------------------------
# Scoped by source_file + "no gold_reconciliation_summary row" rather than a
# single statement_id, since an exceptions-only vendor's rows may span more
# than one orphaned statement_id (e.g. more than one review-queue flag
# raised before that vendor's PDF ever got a full pipeline run) -- see
# get_exceptions_only_vendor().

_ORPHAN_EXCEPTIONS_WHERE = """
    ge.source_file = ?
    AND NOT EXISTS (
        SELECT 1 FROM gold_reconciliation_summary s
        WHERE s.statement_id = ge.statement_id
    )
"""


def get_open_exceptions_for_source_file(source_file: str, reason_filter: str = None) -> list:
    reason = _REASON_FILTER_SQL.get(reason_filter)
    if reason:
        return _with_aging_fields(execute_query(
            _OPEN_EXCEPTIONS_SELECT + f"""
            WHERE {_ORPHAN_EXCEPTIONS_WHERE} AND ge.exception_status = 'OPEN' AND ge.exception_reason = ?
            ORDER BY ge.invoice_number
            """,
            [source_file, reason],
        ))
    return _with_aging_fields(execute_query(
        _OPEN_EXCEPTIONS_SELECT + f"""
        WHERE {_ORPHAN_EXCEPTIONS_WHERE} AND ge.exception_status = 'OPEN'
        ORDER BY ge.invoice_number
        """,
        [source_file],
    ))


def get_exception_counts_for_source_file(source_file: str):
    total = execute_query(
        f"SELECT COUNT(*) AS c FROM gold_exceptions ge WHERE {_ORPHAN_EXCEPTIONS_WHERE}",
        [source_file],
    )[0]["c"] or 0
    resolved = execute_query(
        f"""
        SELECT COUNT(*) AS c FROM gold_exceptions ge
        WHERE {_ORPHAN_EXCEPTIONS_WHERE} AND ge.exception_status != 'OPEN'
        """,
        [source_file],
    )[0]["c"] or 0
    return total, resolved


def _recompute_summary_counts(statement_id: str) -> None:
    """Keeps gold_reconciliation_summary.exception_count/overall_status
    truthful whenever the live OPEN count for statement_id changes --
    called by resolve_exception() (and so, transitively, by
    bulk_approve_exceptions(), which resolves each candidate through that
    same function) right after RESOLVING one, and by action_review_item()
    right after RAISING a new one (a flagged review-queue row can
    undercount an existing summary just as easily as a resolution can
    overcount it).

    Without this, the summary row keeps whatever count matching wrote at
    reconciliation time forever, even once a later event makes it wrong --
    see PIPELINE_VERIFICATION_REPORT.md Finding 2 (reproduced live: after
    calling resolve_exception(), the raw table still showed the old count
    while the real OPEN count had already dropped by one). Every UI-facing
    read already works around this by live-querying gold_exceptions
    instead (Claude.md Rule 3) -- this fixes the table itself at the
    source, for the one real reader that doesn't apply that workaround
    (notebooks/04_generate_report.py). A statement_id with no
    gold_reconciliation_summary row (e.g. an exceptions-only vendor -- see
    _get_exceptions_only_vendors(), or a review-queue item flagged before
    its statement ever reached a full pipeline run) makes this UPDATE a
    harmless no-op.
    """
    live_count = execute_query(
        "SELECT COUNT(*) AS c FROM gold_exceptions WHERE statement_id = ? AND exception_status = 'OPEN'",
        [statement_id],
    )[0]["c"] or 0
    execute_sql(
        "UPDATE gold_reconciliation_summary SET exception_count = ?, overall_status = ? WHERE statement_id = ?",
        [live_count, score_overall_status(live_count), statement_id],
    )


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
    _recompute_summary_counts(statement_id)


def escalate_exception(exception_id: str, escalated_by: str) -> None:
    """Marks an exception ESCALATED -- see exceptions_review.html's
    "Escalate" button. Does not touch exception_status: an escalated
    exception is still OPEN, just flagged for follow-up, not resolved."""
    now = datetime.now(timezone.utc).isoformat()
    execute_sql(
        """
        UPDATE gold_exceptions
        SET escalation_status = 'ESCALATED', escalated_by = ?, escalated_at = ?
        WHERE exception_id = ?
        """,
        [escalated_by, now, exception_id],
    )


def get_exception_aging_summary(vendor_name: str):
    """{"oldest_date_raised": ..., "days_open": ...} for this vendor's
    oldest OPEN exception, or None if there are none -- see
    exceptions_vendors.html's "Oldest: N days open" vendor card note.
    Mirrors the same statement-vs-exceptions-only-vendor branching as
    exceptions_review() in web/routers/exceptions.py."""
    statement = get_vendor_latest_statement(vendor_name)
    if statement:
        rows = execute_query(
            """
            SELECT MIN(date_raised) AS oldest_date_raised FROM gold_exceptions
            WHERE statement_id = ? AND exception_status = 'OPEN'
            """,
            [statement["statement_id"]],
        )
    else:
        statement = get_exceptions_only_vendor(vendor_name)
        if not statement:
            return None
        rows = execute_query(
            f"""
            SELECT MIN(ge.date_raised) AS oldest_date_raised FROM gold_exceptions ge
            WHERE {_ORPHAN_EXCEPTIONS_WHERE} AND ge.exception_status = 'OPEN'
            """,
            [statement["source_file"]],
        )

    oldest = rows[0]["oldest_date_raised"] if rows else None
    if not oldest:
        return None
    return {"oldest_date_raised": oldest, "days_open": _days_since(oldest)}


def get_high_confidence_exception_count(vendor_name: str, threshold: float = 0.99) -> int:
    """Count of OPEN exceptions for this vendor with match_confidence
    >= threshold — drives whether the "Bulk approve" button shows on the
    exceptions review page. match_confidence is written by the matching
    engine (src/matching/engine.py's EXCEPTION_MATCH_CONFIDENCE, see
    migrations/008_add_match_confidence.sql) and by a couple of
    non-matching-engine write sites that raise exceptions directly (see
    notebooks/01_document_intake.py:write_skip_exception() and
    action_review_item() below) — rows from any other write site, or
    written before this column existed, have match_confidence = NULL;
    NULL >= threshold is false in SQL, so those are excluded with no
    special-casing needed here.

    Note: today's highest exception match_confidence is 0.90 (Invoice
    Missing), so at the default threshold of 0.99 this — and therefore
    the Bulk approve button — will not surface for real exceptions yet.
    That's intentional: 0.99 is deliberately the safest possible default,
    not tuned to today's scoring scale.

    Mirrors the same statement-vs-exceptions-only-vendor branching as
    exceptions_review() in web/routers/exceptions.py."""
    statement = get_vendor_latest_statement(vendor_name)
    if statement:
        rows = execute_query(
            """
            SELECT COUNT(*) AS c FROM gold_exceptions
            WHERE statement_id = ? AND exception_status = 'OPEN' AND match_confidence >= ?
            """,
            [statement["statement_id"], threshold],
        )
        return rows[0]["c"] or 0

    statement = get_exceptions_only_vendor(vendor_name)
    if not statement:
        return 0
    rows = execute_query(
        f"""
        SELECT COUNT(*) AS c FROM gold_exceptions ge
        WHERE {_ORPHAN_EXCEPTIONS_WHERE} AND ge.exception_status = 'OPEN' AND ge.match_confidence >= ?
        """,
        [statement["source_file"], threshold],
    )
    return rows[0]["c"] or 0


def bulk_approve_exceptions(vendor_name: str, threshold: float, reviewed_by: str) -> int:
    """Marks every OPEN exception for this vendor with match_confidence
    >= threshold as RESOLVED/ACCEPTED, via the same disposition write
    (exception_dispositions insert + gold_exceptions update) a single
    Accept click uses — see resolve_exception(). Returns the number of
    exceptions approved."""
    statement = get_vendor_latest_statement(vendor_name)
    if statement:
        candidates = execute_query(
            """
            SELECT * FROM gold_exceptions
            WHERE statement_id = ? AND exception_status = 'OPEN' AND match_confidence >= ?
            """,
            [statement["statement_id"], threshold],
        )
    else:
        statement = get_exceptions_only_vendor(vendor_name)
        if not statement:
            return 0
        candidates = execute_query(
            f"""
            SELECT ge.* FROM gold_exceptions ge
            WHERE {_ORPHAN_EXCEPTIONS_WHERE} AND ge.exception_status = 'OPEN' AND ge.match_confidence >= ?
            """,
            [statement["source_file"], threshold],
        )

    for exc in candidates:
        resolve_exception(
            exception_id=exc["exception_id"],
            statement_id=exc["statement_id"],
            vendor_name=vendor_name,
            invoice_number=exc["invoice_number"],
            reason_code=exc["exception_reason"],
            disposition_status="ACCEPTED",
            notes=f"Bulk approved — confidence >= {threshold}",
            disposed_by=reviewed_by,
        )

    return len(candidates)


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

def create_job(job_id: str, pdf_filename: str, pdf_path: str, submitted_by: str,
                batch_id: str = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    execute_sql(
        """
        INSERT INTO jobs (job_id, pdf_filename, pdf_path, status, submitted_by, submitted_at, batch_id)
        VALUES (?, ?, ?, 'PENDING', ?, ?, ?)
        """,
        [job_id, pdf_filename, pdf_path, submitted_by, now, batch_id],
    )


def claim_next_pending_job():
    """Atomically claims the oldest PENDING job whose pdf_filename has no
    other job currently PROCESSING, flipping it straight to PROCESSING in
    one UPDATE, then looks it up by the claim_token that UPDATE just
    stamped on it. Returns None if the queue is empty or every remaining
    PENDING job shares a filename with something already in flight.

    This has to be one statement rather than a SELECT-then-UPDATE: with
    several worker threads polling at once (see web/worker.py's worker
    pool), a separate SELECT and UPDATE leaves a window where two workers
    read the same eligible row before either writes, so both claim it.

    Serialization is scoped to pdf_filename, not the whole table. Until
    2026-07-24 this guard refused to claim ANYTHING while any job was
    PROCESSING (docs/INVARIANTS.md's original INV-05) — that was broader
    than the actual failure mode it existed to prevent: two jobs for the
    SAME PDF running concurrently, each missing the other's
    extraction_cache write and both re-running the full AI extraction (see
    TestClaimNextPendingJobIsAtomic in tests/test_web_queries.py). Scoping
    the NOT EXISTS check to pdf_filename keeps that exact protection while
    letting the worker pool actually run different statements in parallel
    — see docs/INVARIANTS.md's amended INV-05 entry for the engineer
    decision behind this change.

    Ordering is by the unique autoincrement id (submission order) rather
    than MIN(submitted_at) — two jobs created in quick succession can land
    on the exact same submitted_at timestamp (datetime.now() resolution
    isn't fine-grained enough to guarantee two close-together calls differ,
    especially on Windows), which would make that WHERE clause match both
    rows and claim them together. id has no such tie. MIN(...) is used
    instead of LIMIT 1 inside the subquery so this stays valid T-SQL if
    this ever runs against Azure SQL (see src/lakehouse/connection.py)."""
    claim_token = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    execute_sql(
        """
        UPDATE jobs SET status = 'PROCESSING', started_at = ?, claim_token = ?
        WHERE id = (
            SELECT MIN(p.id) FROM jobs p
            WHERE p.status = 'PENDING'
              AND NOT EXISTS (
                  SELECT 1 FROM jobs busy
                  WHERE busy.status = 'PROCESSING'
                    AND busy.pdf_filename = p.pdf_filename
              )
        )
        AND status = 'PENDING'
        """,
        [now, claim_token],
    )
    rows = execute_query("SELECT * FROM jobs WHERE claim_token = ?", [claim_token])
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
# Batches (Event Grid auto-intake grouping — see migrations/007 and
# web/routers/intake_trigger.py, which stamps one batch_id per webhook
# delivery). Manual /upload jobs have batch_id = NULL.
# ---------------------------------------------------------------------------

def _format_duration(total_seconds: float) -> str:
    seconds = int(total_seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _stats_for_statement(statement_id):
    """(invoice_count, open_exception_count) for one statement_id, or
    (0, 0) if the job hasn't reached COMPLETED yet (no statement_id) or
    the summary row isn't found. Reuses _live_open_exception_count so a
    resolved exception drops out of the batch total the same way it does
    everywhere else in this file."""
    if not statement_id:
        return 0, 0
    summary_rows = execute_query(
        "SELECT total_invoice_count FROM gold_reconciliation_summary WHERE statement_id = ?",
        [statement_id],
    )
    invoice_count = summary_rows[0]["total_invoice_count"] if summary_rows else 0
    return invoice_count or 0, _live_open_exception_count(statement_id)


def _batch_status(batch: dict) -> str:
    if batch["active_count"]:
        return "PROCESSING"
    if batch["failed_count"]:
        return "PARTIAL"
    return "COMPLETED"


def _batch_time_taken(batch: dict):
    """Wall-clock from the first job's submitted_at to the last job's
    completed_at — only meaningful once every job in the batch has
    finished (COMPLETED or FAILED); a still-PROCESSING batch has no
    end time yet, so this returns None rather than a partial duration."""
    if batch["active_count"] or not batch["last_completed_at"]:
        return None
    start = _parse_datetime(batch["submitted_at"])
    end = _parse_datetime(batch["last_completed_at"])
    return _format_duration((end - start).total_seconds())


def _job_time_taken(job: dict):
    """Wall-clock from this job's started_at (submitted_at if it was
    somehow never claimed) to completed_at. None while still
    PENDING/PROCESSING."""
    if not job["completed_at"]:
        return None
    start = _parse_datetime(job["started_at"] or job["submitted_at"])
    end = _parse_datetime(job["completed_at"])
    return _format_duration((end - start).total_seconds())


def get_all_batches() -> list:
    """One row per batch_id, newest first, with aggregated file/invoice/
    exception counts, overall status, and total time taken."""
    batches = execute_query(
        """
        SELECT
            batch_id,
            COUNT(*) AS total_files,
            SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed_count,
            SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed_count,
            SUM(CASE WHEN status IN ('PENDING', 'PROCESSING') THEN 1 ELSE 0 END) AS active_count,
            MIN(submitted_at) AS submitted_at,
            MAX(completed_at) AS last_completed_at
        FROM jobs
        WHERE batch_id IS NOT NULL
        GROUP BY batch_id
        ORDER BY MIN(submitted_at) DESC
        """
    )

    for batch in batches:
        batch["status"] = _batch_status(batch)
        batch["time_taken"] = _batch_time_taken(batch)

        statement_ids = execute_query(
            "SELECT statement_id FROM jobs WHERE batch_id = ? AND statement_id IS NOT NULL",
            [batch["batch_id"]],
        )
        stats = [_stats_for_statement(row["statement_id"]) for row in statement_ids]
        batch["total_invoices"] = sum(s[0] for s in stats)
        batch["total_exceptions"] = sum(s[1] for s in stats)

    return batches


def get_batch_detail(batch_id: str) -> dict:
    """{"batch": {...summary...}, "jobs": [...]} for one batch_id, or
    {"batch": None, "jobs": []} if the batch_id doesn't exist. Each job
    dict is enriched with invoice_count/exception_count/time_taken for
    the per-file rows on the batch detail page."""
    jobs = execute_query(
        "SELECT * FROM jobs WHERE batch_id = ? ORDER BY submitted_at",
        [batch_id],
    )
    if not jobs:
        return {"batch": None, "jobs": []}

    for job in jobs:
        invoice_count, exception_count = _stats_for_statement(job["statement_id"])
        job["invoice_count"] = invoice_count
        job["exception_count"] = exception_count
        job["time_taken"] = _job_time_taken(job)

    completed_ats = [j["completed_at"] for j in jobs if j["completed_at"]]
    batch = {
        "batch_id": batch_id,
        "total_files": len(jobs),
        "completed_count": sum(1 for j in jobs if j["status"] == "COMPLETED"),
        "failed_count": sum(1 for j in jobs if j["status"] == "FAILED"),
        "active_count": sum(1 for j in jobs if j["status"] in ("PENDING", "PROCESSING")),
        "submitted_at": min(j["submitted_at"] for j in jobs),
        "last_completed_at": max(completed_ats) if completed_ats else None,
        "total_invoices": sum(j["invoice_count"] for j in jobs),
        "total_exceptions": sum(j["exception_count"] for j in jobs),
    }
    batch["status"] = _batch_status(batch)
    batch["time_taken"] = _batch_time_taken(batch)

    return {"batch": batch, "jobs": jobs}


def get_manual_uploads() -> list:
    """Jobs with batch_id = NULL (manual /upload submissions), grouped by
    submission date (newest date first, newest job first within a date)
    for the /batches page's "Manual uploads" section."""
    jobs = execute_query("SELECT * FROM jobs WHERE batch_id IS NULL ORDER BY submitted_at DESC")

    groups = {}
    for job in jobs:
        date_key = job["submitted_at"][:10]
        groups.setdefault(date_key, []).append(job)

    return [{"date": date_key, "jobs": jobs_for_date} for date_key, jobs_for_date in groups.items()]


def get_recent_completed_batches(limit: int = 3) -> list:
    """Last `limit` finished batches (COMPLETED or PARTIAL — no jobs still
    PENDING/PROCESSING), newest first, for the home dashboard's "Recent
    batches" section. Reuses get_all_batches() rather than re-deriving
    batch status with a second query."""
    limit = int(limit)
    finished = [b for b in get_all_batches() if b["status"] != "PROCESSING"]
    return finished[:limit]


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


# ---------------------------------------------------------------------------
# Review queue (validation_document_review_queue)
# ---------------------------------------------------------------------------
# Rows here never get an AI-detected vendor_id/vendor_name (see
# notebooks/01_document_intake.py write_to_review_queue(), which only ever
# writes source_file/statement_id) -- so, per the caller's direction,
# source_file stands in as the vendor grouping key, the same way
# vendor_name is the grouping key for gold_exceptions in the section above.

def _parse_review_row(row: dict) -> dict:
    """Attaches the parsed raw_payload dict plus its invoice_number/amount
    (the fields the sidebar and detail panel need) onto the row, tolerating
    malformed JSON rather than raising."""
    try:
        payload = json.loads(row["raw_payload"]) if row.get("raw_payload") else {}
    except (TypeError, ValueError):
        payload = {}
    row["payload"] = payload
    row["invoice_number"] = payload.get("invoice_number")
    amount = payload.get("outstanding_amount")
    row["amount"] = amount if amount is not None else payload.get("amount")
    return row


def get_pending_review_count() -> int:
    rows = execute_query(
        "SELECT COUNT(*) AS c FROM validation_document_review_queue WHERE review_status = 'PENDING_REVIEW'"
    )
    return rows[0]["c"] or 0 if rows else 0


def get_review_queue_vendors() -> list:
    """One row per source_file with pending review rows, plus a
    rejection_category breakdown for that source_file's footer note."""
    rows = execute_query(
        """
        SELECT source_file, COUNT(*) AS pending_count
        FROM validation_document_review_queue
        WHERE review_status = 'PENDING_REVIEW'
        GROUP BY source_file
        ORDER BY source_file
        """
    )
    for row in rows:
        cat_rows = execute_query(
            """
            SELECT rejection_category, COUNT(*) AS c
            FROM validation_document_review_queue
            WHERE source_file = ? AND review_status = 'PENDING_REVIEW'
            GROUP BY rejection_category
            """,
            [row["source_file"]],
        )
        row["category_breakdown"] = {r["rejection_category"]: r["c"] for r in cat_rows}
    return rows


def get_review_queue_for_vendor(source_file: str) -> list:
    rows = execute_query(
        """
        SELECT * FROM validation_document_review_queue
        WHERE source_file = ? AND review_status = 'PENDING_REVIEW'
        ORDER BY id
        """,
        [source_file],
    )
    return [_parse_review_row(r) for r in rows]


def get_review_queue_item(review_id: str):
    rows = execute_query(
        "SELECT * FROM validation_document_review_queue WHERE review_id = ?",
        [review_id],
    )
    return _parse_review_row(rows[0]) if rows else None


def action_review_item(review_id: str, action: str, reviewed_by: str) -> None:
    """Approves or flags a review queue row. Flagging also raises a
    gold_exceptions row so the item surfaces on the normal exceptions page
    too -- DUPLICATE_RECORD keeps its own reason so it reads distinctly
    from EXTRACTION_INCOMPLETE (every other rejection_category, e.g.
    MISSING_MANDATORY_FIELD, is genuinely an incomplete extraction)."""
    item = get_review_queue_item(review_id)
    if not item:
        return
    now = datetime.now(timezone.utc).isoformat()
    status = "APPROVED" if action == "approve" else "FLAGGED"
    execute_sql(
        """
        UPDATE validation_document_review_queue
        SET review_status = ?, reviewed_by = ?, reviewed_timestamp = ?
        WHERE review_id = ?
        """,
        [status, reviewed_by, now, review_id],
    )
    if action == "flag":
        exception_reason = (
            "DUPLICATE_RECORD" if item["rejection_category"] == "DUPLICATE_RECORD"
            else "EXTRACTION_INCOMPLETE"
        )
        # Step 7 only specifies a match_confidence score for
        # EXTRACTION_INCOMPLETE — DUPLICATE_RECORD stays NULL rather than
        # guessing a number that wasn't asked for.
        match_confidence = (
            score_exception_confidence("EXTRACTION_INCOMPLETE")
            if exception_reason == "EXTRACTION_INCOMPLETE" else None
        )
        execute_sql(
            """
            INSERT INTO gold_exceptions (
                exception_id, invoice_number, statement_amount, erp_amount,
                match_status, exception_reason, exception_status,
                source_file, statement_id, date_raised, statement_period,
                ai_explanation, match_confidence, shop_owner
            ) VALUES (?, ?, ?, NULL, 'EXCEPTION', ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(uuid.uuid4()),
                item["invoice_number"],
                item["amount"],
                exception_reason,
                item["source_file"],
                item["statement_id"],
                now,
                item["statement_period"],
                item["rejection_details"],
                match_confidence,
                get_shop_owner(item.get("vendor_id")),
            ],
        )
        # A newly-raised OPEN exception can undercount an existing
        # gold_reconciliation_summary row the same way a resolution can
        # overcount it — see _recompute_summary_counts()'s docstring. A
        # no-op if this statement_id has no summary row yet (the common
        # case: review-queue items are usually raised before a statement
        # ever reaches a full pipeline run).
        _recompute_summary_counts(item["statement_id"])
