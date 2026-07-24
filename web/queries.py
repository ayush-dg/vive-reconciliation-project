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
        return execute_query(
            _OPEN_EXCEPTIONS_SELECT + f"""
            WHERE {_ORPHAN_EXCEPTIONS_WHERE} AND ge.exception_status = 'OPEN' AND ge.exception_reason = ?
            ORDER BY ge.invoice_number
            """,
            [source_file, reason],
        )
    return execute_query(
        _OPEN_EXCEPTIONS_SELECT + f"""
        WHERE {_ORPHAN_EXCEPTIONS_WHERE} AND ge.exception_status = 'OPEN'
        ORDER BY ge.invoice_number
        """,
        [source_file],
    )


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
    """Atomically claims the oldest PENDING job by flipping it straight to
    PROCESSING in one UPDATE, then looks it up by the claim_token that
    UPDATE just stamped on it.

    This has to be one statement rather than a SELECT-then-UPDATE: with two
    worker processes polling at once (e.g. a second server instance left
    running from an earlier session), a separate SELECT and UPDATE leaves a
    window where both can read the same PENDING row before either writes,
    so both claim it — or each claims a different job for the same
    just-uploaded PDF and runs it concurrently, so neither sees the other's
    extraction_cache write in time and both re-run the full AI extraction.
    The NOT EXISTS guard also means only one job is ever PROCESSING
    system-wide, so a second upload of an identical PDF always waits for
    the first run to fully commit (including its cache write) before its
    own cache check runs. Ordering is by the unique autoincrement id
    (submission order) rather than MIN(submitted_at) — two jobs created in
    quick succession can land on the exact same submitted_at timestamp
    (datetime.now() resolution isn't fine-grained enough to guarantee two
    close-together calls differ, especially on Windows), which would make
    that WHERE clause match both rows and claim them together. id has no
    such tie. MIN(...) is used instead of LIMIT 1 inside the subquery so
    this stays valid T-SQL if this ever runs against Azure SQL (see
    src/lakehouse/connection.py)."""
    claim_token = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    execute_sql(
        """
        UPDATE jobs SET status = 'PROCESSING', started_at = ?, claim_token = ?
        WHERE id = (SELECT MIN(id) FROM jobs WHERE status = 'PENDING')
          AND status = 'PENDING'
          AND NOT EXISTS (SELECT 1 FROM jobs WHERE status = 'PROCESSING')
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
        execute_sql(
            """
            INSERT INTO gold_exceptions (
                exception_id, invoice_number, statement_amount, erp_amount,
                match_status, exception_reason, exception_status,
                source_file, statement_id, date_raised, statement_period,
                ai_explanation
            ) VALUES (?, ?, ?, NULL, 'EXCEPTION', ?, 'OPEN', ?, ?, ?, ?, ?)
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
            ],
        )
