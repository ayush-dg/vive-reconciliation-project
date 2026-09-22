"""
queries.py

All Azure SQL access for the web app, layered on top of
src.lakehouse.connection (the same execute_sql/execute_query helpers the
pipeline itself uses — see that module's docstring for the SQLite/Azure
SQL abstraction). Routers stay thin; this module owns the SQL.
"""

import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.lakehouse.connection import execute_query, execute_sql, execute_query_fabric, execute_sql_fabric
# recon_query/recon_sql: Fabric Warehouse (silver.recon_*) -- see
# migrations/013_add_recon_tables.sql's history (started on the local
# backend, moved to Fabric 2026-08-26 per the user). Used by the Exceptions
# page, the Home page's "Reconciliation runs" panel (get_recent_recon_runs()),
# and now Reports (get_all_runs()/get_statement_report(), switched
# 2026-09-18 -- Reports was the one page still reading the old
# gold_reconciliation_summary/gold_matched_invoices/gold_exceptions tables,
# which the real NetSuite matching flow (src/matching/fabric_matching.py)
# never writes to, so it stayed empty regardless of whether reconciliation
# actually ran). Upload/Batches still use execute_query/execute_sql
# (gold_*/local backend) -- not touched by this change.
from src.lakehouse.fabric_sql import execute_warehouse_query as recon_query, execute_warehouse_sql as recon_sql
from src.matching.engine import score_exception_confidence, score_overall_status
from src.shop_owners import get_shop_owner
from src.vendor_identity import display_name as vendor_display_name

REASON_LABELS = {
    "Invoice Missing": "missing",
    "Amount Mismatch": "amount mismatch",
    "EXTRACTION_INCOMPLETE": "extraction incomplete",
    "Not Found in NetSuite": "not found in NetSuite",
    "Vendor Not Resolved in NetSuite": "vendor not resolved",
}


# ---------------------------------------------------------------------------
# Home / dashboard
# ---------------------------------------------------------------------------

# gold_reconciliation_summary is an append-only per-run snapshot -- it keeps
# a row for every vendor that has EVER completed a run, including ones whose
# jobs-table row has since been deleted (job cleanup scripts, e.g.
# scripts/cleanup_job_history_for_demo.py, only ever touch `jobs` and
# deliberately leave Gold alone). So it's scoped here to only the
# statement_ids that still have a live row in `jobs`. The subquery is
# DISTINCT so this join can't fan out and double-count if a statement_id
# were ever referenced by more than one jobs row.
_CURRENT_STATEMENT_IDS = """
    SELECT DISTINCT statement_id
    FROM jobs
    WHERE statement_id IS NOT NULL
"""

# "Which row is a vendor+period's current one" used to be inferred here via
# a vendor_name + MAX(reconciliation_timestamp) heuristic
# (_LATEST_RUN_PER_VENDOR, removed by migrations/011_add_version_tracking.sql's
# change) -- fragile in both directions: an AI-extracted vendor_name that
# varies slightly between two uploads of the same statement (e.g. "asTech"
# vs. "asTech (Repairify, Inc.)") looked like two different vendors and got
# double-counted, and it had no period awareness at all, so two genuinely
# different periods for the same vendor could collapse to a single "latest"
# row. gold_reconciliation_summary.is_latest_version is now set explicitly
# and deterministically at intake time (notebooks/01_document_intake.py's
# resolve_version_info(), keyed on vendor_id + statement_period, not
# vendor_name) -- a plain `is_latest_version = 1` filter replaces the old
# join everywhere below.


def get_kpis() -> dict:
    """Reads silver.recon_summary (Fabric Warehouse) -- NOT
    gold_reconciliation_summary (Azure SQL), which this used before
    2026-09-22. gold_reconciliation_summary only gets written by the old
    Phase 2 matching path (src/matching/engine.py's run_matching()), which
    requires real voucher/ERP data loaded in Azure SQL -- confirmed live
    that basically no vendor has that loaded, so gold_reconciliation_summary
    has stopped getting new rows entirely and this card was showing all
    zeros despite real, current reconciliation results sitting in
    silver.recon_summary (what Exceptions/Validation already read)."""
    totals = recon_query(
        """
        SELECT
            COALESCE(SUM(s.total_invoice_count), 0) AS total_invoices,
            COALESCE(SUM(s.matched_count), 0) AS auto_reconciled,
            COALESCE(SUM(s.statement_total), 0) AS statement_total,
            COUNT(DISTINCT s.vendor_name) AS vendor_count
        FROM silver.recon_summary s
        WHERE s.is_latest_version = 1
        """
    )[0]
    open_exceptions = get_open_recon_exceptions_count()
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


def get_kpi_debug_state() -> dict:
    """TEMPORARY diagnostic (added 2026-08-20 to investigate the Total
    invoices/Statement total KPI cards showing 156 instead of the expected
    273) -- read-only, no writes. Dumps every input get_kpis() actually
    computes from, raw, so the exact live production state can be
    inspected directly instead of inferred from rendered HTML pages.
    Remove once the investigation is closed."""
    jobs = execute_query(
        "SELECT job_id, pdf_filename, status, vendor_name, statement_id, submitted_at, completed_at "
        "FROM jobs ORDER BY submitted_at DESC"
    )
    job_statement_ids = [j["statement_id"] for j in jobs if j["statement_id"]]
    gold_rows_for_jobs = []
    if job_statement_ids:
        placeholders = ", ".join("?" for _ in job_statement_ids)
        gold_rows_for_jobs = execute_query(
            f"""
            SELECT statement_id, vendor_name, total_invoice_count, matched_count,
                   exception_count, statement_total, reconciliation_timestamp,
                   version_number, previous_statement_id, is_latest_version
            FROM gold_reconciliation_summary
            WHERE statement_id IN ({placeholders})
            ORDER BY reconciliation_timestamp DESC
            """,
            job_statement_ids,
        )
    latest_versions = execute_query(
        """
        SELECT vendor_id, vendor_name, statement_period, statement_id, version_number
        FROM gold_reconciliation_summary
        WHERE is_latest_version = 1
        """
    )
    return {
        "jobs": jobs,
        "gold_reconciliation_summary_rows_for_current_jobs": gold_rows_for_jobs,
        "latest_version_rows": latest_versions,
        "get_kpis_result": get_kpis(),
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
        WHERE s.is_latest_version = 1
        ORDER BY s.reconciliation_timestamp DESC
        LIMIT {limit}
        """
    )
    return _with_live_exception_counts(rows)


def get_recent_recon_runs(limit: int = 10) -> list:
    """Home page's "Reconciliation runs" panel -- completed statements that
    have gone through the NetSuite matching flow (src/matching/fabric_matching.py),
    NOT get_recent_runs()'s gold_reconciliation_summary (a different,
    voucher-based flow -- see get_vendor_summaries()'s docstring for the
    same distinction on the Exceptions page).

    Reads silver.recon_summary (Fabric Warehouse) for the reconciliation
    numbers, then a local jobs lookup per row for job_id (recon_summary has
    no job_id column -- jobs lives on a different database engine entirely,
    so this can't be a single query/join). Trusts recon_summary's own
    stored matched_count/exception_count rather than re-deriving live
    counts per row (unlike get_recent_runs()'s _with_live_exception_counts())
    -- an extra Fabric round trip per row on top of the ones this already
    costs would make the Home page even slower for a value that's already
    kept fresh by resolve_exception()'s _recompute_summary_counts() call.

    statement_period is selected from recon_summary above but NOT trusted --
    silver.statement (and therefore recon_summary) has no statement_period
    column at all yet, a dbt-model gap (see get_exception_runs()'s
    docstring, same issue found on the Exceptions page) -- confirmed
    always NULL live. document_intake_log's own statement_period is
    reliably populated instead, so it overrides recon_summary's here,
    batched in one query alongside the existing per-row job_id lookup."""
    rows = recon_query(
        f"""
        SELECT TOP {int(limit)} statement_id, vendor_name, statement_period,
               total_invoice_count, matched_count, exception_count,
               overall_status, reconciliation_timestamp
        FROM silver.recon_summary
        WHERE is_latest_version = 1
        ORDER BY reconciliation_timestamp DESC
        """
    )
    if rows:
        statement_ids = [r["statement_id"] for r in rows]
        placeholders = ", ".join("?" for _ in statement_ids)
        intake_rows = execute_query(
            f"SELECT statement_id, statement_period, shop_or_entity FROM document_intake_log "
            f"WHERE statement_id IN ({placeholders})",
            statement_ids,
        )
        intake_by_statement = {r["statement_id"]: r for r in intake_rows}
        for row in rows:
            intake_row = intake_by_statement.get(row["statement_id"])
            row["statement_period"] = (intake_row["statement_period"] if intake_row else None) or row["statement_period"]
            # shop_or_entity is a JSON list (see write_intake_log()) -- same
            # parse pattern as get_exception_runs()'s shop fix (2026-09-21):
            # silver.recon_summary/statement have no populated shop field.
            try:
                shop_list = json.loads(intake_row["shop_or_entity"]) if intake_row and intake_row.get("shop_or_entity") else []
            except (TypeError, ValueError):
                shop_list = []
            row["shop"] = ", ".join(shop_list) if shop_list else None

    for row in rows:
        job_rows = execute_query(
            "SELECT job_id FROM jobs WHERE statement_id = ? ORDER BY submitted_at DESC LIMIT 1",
            [row["statement_id"]],
        )
        row["job_id"] = job_rows[0]["job_id"] if job_rows else None
        row["vendor_display_name"] = vendor_display_name(row["vendor_name"])
    return rows


def get_open_exceptions_count() -> int:
    """
    Live count of OPEN gold_exceptions rows, scoped to each vendor+period's
    latest version only (gold_reconciliation_summary.is_latest_version,
    same scoping get_kpis()/get_recent_runs() already use) — a flat,
    unscoped COUNT(*) here would also pick up exceptions still OPEN on a
    superseded version of the same vendor/period (e.g. a statement
    re-uploaded after a correction, or re-run several times while
    debugging a cache/connectivity issue, producing multiple
    statement_ids), which the recent-runs table correctly excludes.
    Without this scoping, this KPI and the table's per-row
    exception_count (see _with_live_exception_counts()) disagree — the
    whole point of both is to describe the same "open exceptions right
    now" state.

    Called from sidebar_context() on every page (see web/deps.py) -- wrapped
    in a broad try/except so a transient DB/connectivity failure here only
    degrades the sidebar's nav-dot count to 0 instead of taking down every
    page in the app (same defensive posture as get_pending_review_count()
    below, added 2026-08-29 after a Fabric auth failure here crashed
    /exceptions, /upload, and /jobs/history in production)."""
    try:
        rows = execute_query(
            """
            SELECT COUNT(*) AS c
            FROM gold_exceptions ge
            INNER JOIN gold_reconciliation_summary s ON ge.statement_id = s.statement_id
            WHERE ge.exception_status = 'OPEN' AND s.is_latest_version = 1
            """
        )
        return rows[0]["c"] or 0 if rows else 0
    except Exception as e:
        print(f"[queries] get_open_exceptions_count failed, defaulting to 0: {e}")
        return 0


def get_open_recon_exceptions_count() -> int:
    """Live count of OPEN recon_exceptions rows (see
    src/matching/fabric_matching.py), same is_latest_version scoping as
    get_open_exceptions_count(). Used only for the sidebar's Exceptions
    nav-item dot (web/deps.py sidebar_context()) -- kept separate from
    get_open_exceptions_count() rather than repointing that function,
    since it's shared with get_kpis()'s Home dashboard card, which stays
    on gold_exceptions (scoped with the user 2026-08-26: only the
    Exceptions page itself moves to recon_*, not Home/Reports)."""
    rows = recon_query(
        """
        SELECT COUNT(*) AS c
        FROM silver.recon_exceptions ge
        INNER JOIN silver.recon_summary s ON ge.statement_id = s.statement_id
        WHERE ge.exception_status = 'OPEN' AND s.is_latest_version = 1
        """
    )
    return rows[0]["c"] or 0 if rows else 0


def _live_total_invoice_count(statement_id: str) -> int:
    """Live count of every invoice this statement produced (Matched +
    Exceptions, any status) -- the same total the report detail page shows
    (see get_statement_report()'s matched/exceptions arrays). Replaces
    gold_reconciliation_summary's cached total_invoice_count, which goes
    stale for the same reason exception_count does (see
    _live_open_exception_count()'s docstring): run_matching() computes it
    as len(stmt_rows) -- a count of Silver VENDOR_STATEMENT rows only --
    before intake's write_skip_exception() rows (raised straight to
    gold_exceptions for a row with no invoice identifier at all, never
    reaching Silver -- see notebooks/01_document_intake.py's
    get_skip_reason()) are counted at all."""
    rows = execute_query(
        """
        SELECT
            (SELECT COUNT(*) FROM gold_matched_invoices WHERE statement_id = ?) +
            (SELECT COUNT(*) FROM gold_exceptions WHERE statement_id = ?) AS c
        """,
        [statement_id, statement_id],
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
    """Overwrites exception_count/overall_status/total_invoice_count on each
    row (as returned by a gold_reconciliation_summary query) with live
    counts — see _live_open_exception_count() and
    _live_total_invoice_count(). overall_status only ever needs to
    distinguish RECONCILED from not here — every consumer template
    (home.html, reports.html) renders any non-RECONCILED value identically
    as a generic "Exceptions" badge."""
    for row in rows:
        count = _live_open_exception_count(row["statement_id"])
        row["exception_count"] = count
        row["overall_status"] = "RECONCILED" if count == 0 else "EXCEPTIONS_PRESENT"
        row["total_invoice_count"] = _live_total_invoice_count(row["statement_id"])
    return rows


# ---------------------------------------------------------------------------
# Exceptions — vendors overview
# ---------------------------------------------------------------------------

def get_vendor_summaries() -> list:
    """One row per vendor: their most recent reconciliation run, plus a
    breakdown of open-exception reasons for that run's footer note.

    Still collapses to one card per vendor_name (this page's detail route,
    get_vendor_latest_statement(), looks a vendor up by vendor_name alone
    -- making this list period-aware without also changing that lookup
    would let two cards for the same vendor point at the same single
    detail page, a worse inconsistency than the one being fixed here).
    What changed: is_latest_version = 1 is applied FIRST, so a superseded
    duplicate upload (same vendor_id + statement_period re-uploaded --
    see migrations/011_add_version_tracking.sql) is excluded before the
    "most recent wins" collapse runs, instead of being able to win that
    collapse and silently stand in for the version it actually supersedes.

    Also includes "exceptions-only" vendors: ones with OPEN gold_exceptions
    rows raised against a statement_id that never got a
    gold_reconciliation_summary row at all -- e.g. a review-queue row
    flagged via action_review_item() before that vendor's PDF finished a
    full pipeline run (see web/routers/review_queue.py). Without this,
    such a vendor's exceptions are real and OPEN but never show up on the
    exceptions page — the vendor cards only ever queried
    gold_reconciliation_summary. See _get_exceptions_only_vendors()."""
    # NOTE: recon_summary/recon_exceptions (new NetSuite matching flow --
    # see src/matching/fabric_matching.py), NOT gold_reconciliation_summary/
    # gold_exceptions. That old-engine data is untouched by this page now --
    # scoped this way deliberately with the user 2026-08-26, since gold_*
    # reflects a different (voucher-based) matching flow this page no
    # longer shows. Home dashboard KPIs and Reports still read gold_*.
    rows = recon_query(
        """
        SELECT statement_id, vendor_name, statement_period, total_invoice_count,
               matched_count, exception_count, statement_total, overall_status,
               reconciliation_timestamp
        FROM silver.recon_summary
        WHERE is_latest_version = 1
        ORDER BY reconciliation_timestamp ASC
        """
    )
    latest_by_vendor = {}
    for row in rows:
        latest_by_vendor[row["vendor_name"]] = row  # later (ASC) rows win
    vendors = list(latest_by_vendor.values())

    # Batched (was one recon_query() call per vendor) -- each recon_query()
    # call is a fresh Fabric round-trip (~4-8s measured, dominated by AAD
    # auth before fabric_sql.py's credential caching fix), so N per-vendor
    # calls here directly multiplied the exceptions page's load time by N.
    # See 2026-09-02 investigation: 4 vendors, ~55s total. Empty-`vendors`
    # guard below avoids emitting "IN ()", invalid SQL on both SQLite and
    # T-SQL.
    if vendors:
        statement_ids = [v["statement_id"] for v in vendors]
        placeholders = ", ".join("?" for _ in statement_ids)
        reason_rows = recon_query(
            f"""
            SELECT statement_id, exception_reason, COUNT(*) AS c
            FROM silver.recon_exceptions
            WHERE statement_id IN ({placeholders}) AND exception_status = 'OPEN'
            GROUP BY statement_id, exception_reason
            """,
            statement_ids,
        )
        reasons_by_statement = {}
        for r in reason_rows:
            reasons_by_statement.setdefault(r["statement_id"], []).append(r)

        for vendor in vendors:
            rows_for_vendor = reasons_by_statement.get(vendor["statement_id"], [])
            vendor["reason_breakdown"] = {
                REASON_LABELS.get(r["exception_reason"], r["exception_reason"]): r["c"]
                for r in rows_for_vendor
            }
            # Live count (sum of the OPEN breakdown just fetched above) —
            # replaces the stale exception_count from gold_reconciliation_summary,
            # which matching writes once from Silver-classified exceptions only
            # and never updates again. See _live_open_exception_count().
            vendor["exception_count"] = sum(r["c"] for r in rows_for_vendor)

    vendors.extend(_get_exceptions_only_vendors())
    _attach_aging_summaries(vendors)
    for vendor in vendors:
        vendor["vendor_display_name"] = vendor_display_name(vendor["vendor_name"])
    return sorted(vendors, key=lambda v: v["vendor_name"] or "")


def get_exception_runs() -> list:
    """One row per statement RUN (every PDF ever reconciled), not one per
    vendor -- see get_vendor_summaries() for the older vendor-rollup
    version this sits alongside (still used internally by
    bulk_approve_exceptions()/get_high_confidence_exception_count(), which
    are genuinely vendor-wide operations, not per-run). This is what the
    Exceptions overview page itself renders now, per the user 2026-09-21:
    one card per upload, in vendor/shop/location/period order, so a vendor
    with several shops (or several periods) shows all of them instead of
    only its single most-recently-reconciled run.

    No is_latest_version filter -- deliberately shows every run, not just
    the current version per vendor+period (unlike get_vendor_summaries()),
    since browsing period-wise is the point.

    shop comes straight off silver.recon_summary (already written per-run
    by fabric_matching.py's _write_summary()). billing_location AND
    statement_period do NOT reliably live there -- silver.statement (and
    therefore recon_summary) has no statement_period column at all yet
    (see _fetch_statement()'s own comment -- a dbt-model gap, confirmed
    live: always NULL), and billing_location was never written there
    either. Both are intake-time fields on document_intake_log instead
    (confirmed live: reliably populated there, e.g. asTech's
    statement_period='2026-08', billing_location='Manchester, New
    Hampshire') -- joined in via a second batched query, same
    N+1-avoidance pattern as the reason_breakdown/aging batching below."""
    runs = recon_query(
        """
        SELECT statement_id, vendor_name, total_invoice_count,
               matched_count, exception_count, statement_total, overall_status,
               reconciliation_timestamp
        FROM silver.recon_summary
        ORDER BY reconciliation_timestamp DESC
        """
    )

    if runs:
        statement_ids = [r["statement_id"] for r in runs]
        placeholders = ", ".join("?" for _ in statement_ids)
        reason_rows = recon_query(
            f"""
            SELECT statement_id, exception_reason, COUNT(*) AS c
            FROM silver.recon_exceptions
            WHERE statement_id IN ({placeholders}) AND exception_status = 'OPEN'
            GROUP BY statement_id, exception_reason
            """,
            statement_ids,
        )
        reasons_by_statement = {}
        for r in reason_rows:
            reasons_by_statement.setdefault(r["statement_id"], []).append(r)

        # TEMPORARY (2026-08-29): document_intake_log pointed back at Azure
        # SQL -- see get_vendor_name_for_statement()'s comment for why.
        # shop_or_entity added 2026-09-21: silver.recon_summary.shop is
        # never populated (it's sourced from silver.statement.shop_name_raw,
        # itself from bronze.unnested_statement_lines.shop_name -- confirmed
        # live, always NULL across every vendor/statement, since extraction
        # has no per-line "shop" field on most vendor PDFs). document_intake_log's
        # shop_or_entity IS reliably populated at intake time -- same JSON-list
        # column, same parse pattern get_statement_report() already uses.
        intake_rows = execute_query(
            f"""
            SELECT statement_id, billing_location, statement_period, shop_or_entity
            FROM document_intake_log
            WHERE statement_id IN ({placeholders})
            """,
            statement_ids,
        )
        intake_by_statement = {r["statement_id"]: r for r in intake_rows}

        for run in runs:
            rows_for_run = reasons_by_statement.get(run["statement_id"], [])
            run["reason_breakdown"] = {
                REASON_LABELS.get(r["exception_reason"], r["exception_reason"]): r["c"]
                for r in rows_for_run
            }
            run["exception_count"] = sum(r["c"] for r in rows_for_run)
            intake_row = intake_by_statement.get(run["statement_id"])
            run["billing_location"] = intake_row["billing_location"] if intake_row else None
            run["statement_period"] = intake_row["statement_period"] if intake_row else None
            try:
                shop_list = json.loads(intake_row["shop_or_entity"]) if intake_row and intake_row.get("shop_or_entity") else []
            except (TypeError, ValueError):
                shop_list = []
            run["shop"] = ", ".join(shop_list) if shop_list else None

    runs.extend(_get_exceptions_only_vendors())
    _attach_aging_summaries(runs)
    for run in runs:
        run["vendor_display_name"] = vendor_display_name(run["vendor_name"])
        run.setdefault("billing_location", None)
        run.setdefault("shop", None)
        run.setdefault("statement_period", None)
    return runs


def _attach_aging_summaries(vendors: list) -> None:
    """Batched equivalent of calling get_exception_aging_summary(vendor_name)
    once per vendor (mutates each vendor dict in place, adding "aging") --
    same 2026-09-02 N+1 fix as the reason_breakdown batching above. Splits
    vendors into the two kinds get_exception_aging_summary() itself
    branches on: summary-backed (real statement_id) vs. exceptions-only
    (no statement_id, keyed by source_file -- see
    _get_exceptions_only_vendors()). Both batches are single set-based
    queries regardless of vendor count. get_exception_aging_summary()
    itself is left unchanged (and still used directly elsewhere/by tests)
    -- this is purely an alternate, batched path for the vendor-list page."""
    for vendor in vendors:
        vendor["aging"] = None

    with_statement = [v for v in vendors if v.get("statement_id")]
    if with_statement:
        statement_ids = [v["statement_id"] for v in with_statement]
        placeholders = ", ".join("?" for _ in statement_ids)
        aging_rows = recon_query(
            f"""
            SELECT statement_id, MIN(date_raised) AS oldest_date_raised
            FROM silver.recon_exceptions
            WHERE statement_id IN ({placeholders}) AND exception_status = 'OPEN'
            GROUP BY statement_id
            """,
            statement_ids,
        )
        oldest_by_statement = {r["statement_id"]: r["oldest_date_raised"] for r in aging_rows}
        for vendor in with_statement:
            oldest = oldest_by_statement.get(vendor["statement_id"])
            if oldest:
                vendor["aging"] = {"oldest_date_raised": oldest, "days_open": _days_since(oldest)}

    exceptions_only = [v for v in vendors if not v.get("statement_id") and v.get("source_file")]
    if exceptions_only:
        source_files = [v["source_file"] for v in exceptions_only]
        placeholders = ", ".join("?" for _ in source_files)
        aging_rows = recon_query(
            f"""
            SELECT ge.source_file, MIN(ge.date_raised) AS oldest_date_raised
            FROM silver.recon_exceptions ge
            WHERE ge.source_file IN ({placeholders}) AND ge.exception_status = 'OPEN'
              AND NOT EXISTS (
                  SELECT 1 FROM silver.recon_summary s
                  WHERE s.statement_id = ge.statement_id
              )
            GROUP BY ge.source_file
            """,
            source_files,
        )
        oldest_by_source_file = {r["source_file"]: r["oldest_date_raised"] for r in aging_rows}
        for vendor in exceptions_only:
            oldest = oldest_by_source_file.get(vendor["source_file"])
            if oldest:
                vendor["aging"] = {"oldest_date_raised": oldest, "days_open": _days_since(oldest)}


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
    orphan_rows = recon_query(
        """
        SELECT ge.source_file, ge.exception_reason, COUNT(*) AS c
        FROM silver.recon_exceptions ge
        WHERE ge.exception_status = 'OPEN'
          AND NOT EXISTS (
              SELECT 1 FROM silver.recon_summary s
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
            "source_file": source_file,
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

def get_statement_by_id(statement_id: str):
    """Statement-shaped lookup for one specific run, same return shape as
    get_vendor_latest_statement() -- used by the review route when a
    get_exception_runs() card (a specific run, not just "the vendor's
    latest") is clicked, so an older run's "Review exceptions" link opens
    that run, not whichever one happens to be the vendor's newest."""
    rows = recon_query(
        """
        SELECT TOP 1 statement_id, vendor_name, statement_period, total_invoice_count,
               matched_count, exception_count, statement_total, overall_status
        FROM silver.recon_summary
        WHERE statement_id = ?
        """,
        [statement_id],
    )
    return rows[0] if rows else None


def get_vendor_latest_statement(vendor_name: str):
    # is_latest_version = 1 (migrations/011_add_version_tracking.sql) so a
    # superseded duplicate upload can never win this lookup just because
    # someone re-ran matching on its old statement_id after the fact and
    # bumped its reconciliation_timestamp -- see get_vendor_summaries()'s
    # docstring for the same reasoning applied to the vendor card list.
    rows = recon_query(
        """
        SELECT TOP 1 statement_id, vendor_name, statement_period, total_invoice_count,
               matched_count, exception_count, statement_total, overall_status
        FROM silver.recon_summary
        WHERE vendor_name = ? AND is_latest_version = 1
        ORDER BY reconciliation_timestamp DESC
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
    orphan_source_files = recon_query(
        """
        SELECT DISTINCT ge.source_file
        FROM silver.recon_exceptions ge
        WHERE ge.exception_status = 'OPEN'
          AND NOT EXISTS (
              SELECT 1 FROM silver.recon_summary s
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

    count_rows = recon_query(
        """
        SELECT COUNT(*) AS c
        FROM silver.recon_exceptions ge
        WHERE ge.source_file = ? AND ge.exception_status = 'OPEN'
          AND NOT EXISTS (
              SELECT 1 FROM silver.recon_summary s
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
    # "Invoice Missing" is the old/legacy gold_exceptions reason string;
    # the current Fabric-based matching engine (src/matching/fabric_matching.py)
    # produces "Not Found in NetSuite" for the same case instead -- confirmed
    # live 2026-09-22 that every current exception uses the new string, so
    # the "Missing" filter tab matching only the old one found 0 rows even
    # though real missing-invoice exceptions existed. Both are matched here
    # so any old data still using the legacy string keeps working too.
    "missing": ["Invoice Missing", "Not Found in NetSuite"],
    "mismatch": ["Amount Mismatch"],
}


_OPEN_EXCEPTIONS_SELECT = """
    SELECT ge.*, NULL AS invoice_date
    FROM silver.recon_exceptions ge
"""
# No invoice_date join here (unlike the old gold_exceptions version) --
# silver_reconciliation_standard lives on Azure SQL/SQLite; the new Silver
# this data is matched against (silver.statement_line) lives in Fabric, a
# different database engine entirely -- no single SQL query can join across
# both. NULL AS invoice_date keeps the column present (friendly_date
# renders it as "—") rather than letting templates hit a missing key.


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
    reasons = _REASON_FILTER_SQL.get(reason_filter)
    if reasons:
        placeholders = ", ".join("?" for _ in reasons)
        return _with_aging_fields(recon_query(
            _OPEN_EXCEPTIONS_SELECT + f"""
            WHERE ge.statement_id = ? AND ge.exception_status = 'OPEN' AND ge.exception_reason IN ({placeholders})
            ORDER BY ge.invoice_number
            """,
            [statement_id, *reasons],
        ))
    return _with_aging_fields(recon_query(
        _OPEN_EXCEPTIONS_SELECT + """
        WHERE ge.statement_id = ? AND ge.exception_status = 'OPEN'
        ORDER BY ge.invoice_number
        """,
        [statement_id],
    ))


def _scalar_count(rows: list) -> int:
    """Unwraps a `SELECT COUNT(*) AS c ...` result. A COUNT(*) query
    always returns exactly one row when it actually runs -- the only way
    rows is empty here is recon_query()'s Fabric-not-configured fallback
    (see src/lakehouse/fabric_sql.py), which every COUNT(*) call site
    needs to tolerate rather than crash on with a raw IndexError."""
    return (rows[0]["c"] or 0) if rows else 0


def get_exception_counts(statement_id: str):
    total = _scalar_count(recon_query(
        "SELECT COUNT(*) AS c FROM silver.recon_exceptions WHERE statement_id = ?", [statement_id]
    ))
    resolved = _scalar_count(recon_query(
        "SELECT COUNT(*) AS c FROM silver.recon_exceptions WHERE statement_id = ? AND exception_status != 'OPEN'",
        [statement_id],
    ))
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
        SELECT 1 FROM silver.recon_summary s
        WHERE s.statement_id = ge.statement_id
    )
"""


def get_open_exceptions_for_source_file(source_file: str, reason_filter: str = None) -> list:
    reasons = _REASON_FILTER_SQL.get(reason_filter)
    if reasons:
        placeholders = ", ".join("?" for _ in reasons)
        return _with_aging_fields(recon_query(
            _OPEN_EXCEPTIONS_SELECT + f"""
            WHERE {_ORPHAN_EXCEPTIONS_WHERE} AND ge.exception_status = 'OPEN' AND ge.exception_reason IN ({placeholders})
            ORDER BY ge.invoice_number
            """,
            [source_file, *reasons],
        ))
    return _with_aging_fields(recon_query(
        _OPEN_EXCEPTIONS_SELECT + f"""
        WHERE {_ORPHAN_EXCEPTIONS_WHERE} AND ge.exception_status = 'OPEN'
        ORDER BY ge.invoice_number
        """,
        [source_file],
    ))


def get_exception_counts_for_source_file(source_file: str):
    total = _scalar_count(recon_query(
        f"SELECT COUNT(*) AS c FROM silver.recon_exceptions ge WHERE {_ORPHAN_EXCEPTIONS_WHERE}",
        [source_file],
    ))
    resolved = _scalar_count(recon_query(
        f"""
        SELECT COUNT(*) AS c FROM silver.recon_exceptions ge
        WHERE {_ORPHAN_EXCEPTIONS_WHERE} AND ge.exception_status != 'OPEN'
        """,
        [source_file],
    ))
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
    live_count = _scalar_count(recon_query(
        "SELECT COUNT(*) AS c FROM silver.recon_exceptions WHERE statement_id = ? AND exception_status = 'OPEN'",
        [statement_id],
    ))
    recon_sql(
        "UPDATE silver.recon_summary SET exception_count = ?, overall_status = ? WHERE statement_id = ?",
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
    recon_sql(
        "UPDATE silver.recon_exceptions SET exception_status = 'RESOLVED', date_resolved = ? WHERE exception_id = ?",
        [now, exception_id],
    )
    _recompute_summary_counts(statement_id)


def escalate_exception(exception_id: str, escalated_by: str) -> None:
    """Marks an exception ESCALATED -- see exceptions_review.html's
    "Escalate" button. Does not touch exception_status: an escalated
    exception is still OPEN, just flagged for follow-up, not resolved."""
    now = datetime.now(timezone.utc).isoformat()
    recon_sql(
        """
        UPDATE silver.recon_exceptions
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
        rows = recon_query(
            """
            SELECT MIN(date_raised) AS oldest_date_raised FROM silver.recon_exceptions
            WHERE statement_id = ? AND exception_status = 'OPEN'
            """,
            [statement["statement_id"]],
        )
    else:
        statement = get_exceptions_only_vendor(vendor_name)
        if not statement:
            return None
        rows = recon_query(
            f"""
            SELECT MIN(ge.date_raised) AS oldest_date_raised FROM silver.recon_exceptions ge
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
        rows = recon_query(
            """
            SELECT COUNT(*) AS c FROM silver.recon_exceptions
            WHERE statement_id = ? AND exception_status = 'OPEN' AND match_confidence >= ?
            """,
            [statement["statement_id"], threshold],
        )
        return _scalar_count(rows)

    statement = get_exceptions_only_vendor(vendor_name)
    if not statement:
        return 0
    rows = recon_query(
        f"""
        SELECT COUNT(*) AS c FROM silver.recon_exceptions ge
        WHERE {_ORPHAN_EXCEPTIONS_WHERE} AND ge.exception_status = 'OPEN' AND ge.match_confidence >= ?
        """,
        [statement["source_file"], threshold],
    )
    return _scalar_count(rows)


def bulk_approve_exceptions(vendor_name: str, threshold: float, reviewed_by: str) -> int:
    """Marks every OPEN exception for this vendor with match_confidence
    >= threshold as RESOLVED/ACCEPTED, via the same disposition write
    (exception_dispositions insert + gold_exceptions update) a single
    Accept click uses — see resolve_exception(). Returns the number of
    exceptions approved."""
    statement = get_vendor_latest_statement(vendor_name)
    if statement:
        candidates = recon_query(
            """
            SELECT * FROM silver.recon_exceptions
            WHERE statement_id = ? AND exception_status = 'OPEN' AND match_confidence >= ?
            """,
            [statement["statement_id"], threshold],
        )
    else:
        statement = get_exceptions_only_vendor(vendor_name)
        if not statement:
            return 0
        candidates = recon_query(
            f"""
            SELECT ge.* FROM silver.recon_exceptions ge
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
    # TEMPORARY (2026-08-29): document_intake_log pointed back at Azure SQL
    # via execute_query() -- the Fabric SQL Database item this used to read
    # is unreachable in production right now (FABRIC_CLIENT_ID lacks Read
    # permission on it). Revert to execute_query_fabric() once that's
    # granted. No trailing LIMIT here (harmless either way: write_intake_log()
    # DELETEs any existing row for this statement_id before inserting, so
    # there's at most one).
    rows = execute_query(
        "SELECT vendor_name FROM document_intake_log WHERE statement_id = ?",
        [statement_id],
    )
    if rows and rows[0]["vendor_name"]:
        return rows[0]["vendor_name"]
    # Falls back to gold_reconciliation_summary (stays on Azure SQL): on a
    # cache hit, the pipeline's run_intake() re-normalizes Bronze->Silver
    # under a new statement_id but never calls write_intake_log() again
    # (see notebooks/01_document_intake.py), so document_intake_log has no
    # row for that statement_id even though the matching engine already
    # wrote the vendor to gold_reconciliation_summary from the Silver rows.
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
                batch_id: str = None, source_blob_path: str = None) -> None:
    """source_blob_path is only ever set for jobs from the mailbox-ingest
    "Sync to Webapp" flow (web/routers/mailbox_sync.py) -- NULL for manual
    uploads and every other existing intake path, since they have no blob
    origin (or, for dropzone/Event-Grid, already download-then-forget it).
    web/worker.py uses it to write a job's outcome back onto its
    originating blob's metadata when the job finishes; NULL means it skips
    that step entirely, nothing to write back to."""
    now = datetime.now(timezone.utc).isoformat()
    execute_sql(
        """
        INSERT INTO jobs (job_id, pdf_filename, pdf_path, status, submitted_by, submitted_at, batch_id, source_blob_path)
        VALUES (?, ?, ?, 'PENDING', ?, ?, ?, ?)
        """,
        [job_id, pdf_filename, pdf_path, submitted_by, now, batch_id, source_blob_path],
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
                       vendor_name: str = None, error_message: str = None,
                       document_hash: str = None) -> None:
    """Builds the SET clause from whichever fields are relevant to this
    transition — PENDING->PROCESSING only sets started_at; COMPLETED/FAILED
    also set completed_at plus their own outcome fields.

    document_hash (2026-09-03) lets _resolve_bronze_statement_id() find a
    cache-hit job's real Bronze statement_id without re-reading the
    original PDF from local disk -- see that function's docstring."""
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
    if document_hash is not None:
        sets.append("document_hash = ?")
        params.append(document_hash)
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


def get_job_by_id(job_id: str):
    rows = execute_query("SELECT * FROM jobs WHERE job_id = ?", [job_id])
    return rows[0] if rows else None


def _resolve_bronze_statement_id(job: dict) -> str:
    """Finds the statement_id that actually holds this job's Bronze rows.

    On a normal (cache-miss) run, that's just job["statement_id"] --
    write_to_bronze() wrote directly under it. But on a cache HIT,
    notebooks/01_document_intake.py's check_cache() means Bronze is never
    rewritten under the new statement_id at all; it stays permanently
    under whichever statement_id *first* extracted this exact file (see
    run_intake()'s cache-hit branch). So a job's own statement_id can
    legitimately have zero Bronze rows even though the file was
    successfully processed.

    Resolution order: (1) job["document_hash"] -- stored on the jobs row
    at completion time since 2026-09-03 (see update_job_status()), the
    same hash run_intake() computes unconditionally before its cache
    check, so this needs no disk access at all; (2) for jobs that predate
    that column, fall back to re-hashing job["pdf_path"] the same way
    run_intake() itself would on a fresh upload -- but uploads are NOT
    guaranteed to still be on local disk (WEBSITES_ENABLE_APP_SERVICE_STORAGE
    is false in production, so local disk is wiped on every container
    restart), so this fallback is best-effort only, kept for any future
    edge case rather than relied on. Either way, once a hash is found,
    look up extraction_cache for the most recent successful (row_count > 0)
    entry for that hash, mirroring notebooks/01_document_intake.py's
    check_cache() query exactly. Falls back to job["statement_id"]
    unchanged if no hash or no cache entry can be found -- a safe
    degradation (an empty/short result) rather than an error."""
    statement_id = job["statement_id"]

    direct_count = execute_query(
        "SELECT COUNT(*) AS c FROM bronze_vendor_statement_raw WHERE statement_id = ?",
        [statement_id],
    )
    if direct_count and direct_count[0]["c"] > 0:
        return statement_id

    document_hash = job.get("document_hash")

    if not document_hash:
        pdf_path = job.get("pdf_path")
        if not pdf_path or not os.path.exists(pdf_path):
            return statement_id
        try:
            with open(pdf_path, "rb") as f:
                document_hash = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            return statement_id

    # TEMPORARY (2026-08-29): extraction_cache pointed back at Azure SQL --
    # see get_vendor_name_for_statement()'s comment above for why. Revert
    # to execute_query_fabric() once the Fabric permission issue is resolved.
    cached_rows = execute_query(
        """
        SELECT statement_id, ingestion_timestamp FROM extraction_cache
        WHERE document_hash = ? AND row_count > 0
        ORDER BY ingestion_timestamp DESC
        """,
        [document_hash],
    )
    return cached_rows[0]["statement_id"] if cached_rows else statement_id


def get_silver_row_count(statement_id: str) -> int:
    """Real row count in silver_reconciliation_standard for statement_id --
    used by web/worker.py's _run_job() to verify a subprocess that exited
    0 and printed a real-looking "Statement ID: ..." line actually
    produced usable data, instead of trusting exit code + regex alone.

    Deliberately Silver, not Bronze: on a cache hit, Bronze rows stay
    under the ORIGINAL statement_id that first extracted the file (see
    notebooks/01_document_intake.py's check_cache()), so a naive Bronze
    count keyed on the new run's own statement_id would read 0 for every
    legitimate cache-hit success, not just genuine zero-invoice
    extractions. Silver is always freshly (re)normalized under the
    current run's statement_id on every run, cache hit or not -- the
    same reasoning resolve_version_info() relies on -- so it's the
    correct place to ask "did this specific run produce real data."
    """
    rows = execute_query(
        "SELECT COUNT(*) AS c FROM silver_reconciliation_standard "
        "WHERE statement_id = ? AND record_source = 'VENDOR_STATEMENT'",
        [statement_id],
    )
    return rows[0]["c"] or 0 if rows else 0


def _prettify_aging_label(key: str) -> str:
    """"aging_over_30" -> "Over 30 Days", "aging_31_60" -> "31-60 Days",
    "aging_pay_this_amount" -> "Pay This Amount" -- generic, not a lookup
    table of specific field names, so a future vendor's own aging_* keys
    get a reasonable label automatically instead of falling back to the
    raw key. Never changes the underlying value, purely cosmetic."""
    label = key[len("aging_"):] if key.startswith("aging_") else key
    label = re.sub(r"(\d+)_(\d+)", r"\1-\2", label)  # "31_60" -> "31-60"
    label = label.replace("_", " ").strip().title()
    if re.fullmatch(r"(Over )?[\d\-]+", label):
        label += " Days"
    return label


class _RowsWithColumns(list):
    """A plain list of row dicts, with the ordered union of every row's
    raw_columns keys attached as `.columns` -- lets extracted_data.html do
    `{% for r in rows %}` exactly as before (this IS the rows list) while
    also reading `rows.columns` for the flat full-data table's header row,
    without jobs.py needing to change how it builds extracted_data.html's
    context (it just does `"rows": queries.get_extracted_rows_for_job(...)`
    today, unchanged).

    `.aging_summary` is the same idea for document_intake_log's
    raw_aging_summary (see get_extracted_rows_for_job()) -- a dict, empty
    when this statement has none, so the template can do a plain
    `{% if rows.aging_summary %}` with no separate context key needed.
    `.aging_summary_display` is the same data as a (label, value) list,
    in printed order, with keys run through _prettify_aging_label() for
    the template to render directly without needing its own logic."""

    def __init__(self, rows, columns, aging_summary=None):
        super().__init__(rows)
        self.columns = columns
        self.aging_summary = aging_summary or {}
        self.aging_summary_display = [
            (_prettify_aging_label(k), v) for k, v in self.aging_summary.items()
        ]


def get_extracted_rows_for_job(job_id: str) -> list:
    """The true raw extraction for Job History's "View extracted data"
    link, read directly from bronze_vendor_statement_raw -- every row and
    column the extractor produced, nothing filtered, merged, or dropped
    (unlike the old Silver+EXTRACTION_INCOMPLETE union this replaced,
    which could show MORE than Bronze for a statement with skipped rows,
    or FEWER on a cache-hit statement whose Bronze rows live under a
    different, earlier statement_id -- see _resolve_bronze_statement_id()).

    Column names are kept as invoice_number/charges/credits/amount_due
    (aliased from Bronze's raw_-prefixed columns) so extracted_data.html's
    existing 4-column summary table doesn't need to change.

    raw_ai_response (the AI-extracted row's full as-printed columns_found
    dict -- see ClaudeSonnetClient._row_to_invoice()'s "_raw_row" -- null
    for python-library/pdfplumber rows, which never produce one, and for
    jobs run before this column started being saved) is parsed into
    raw_columns here so extracted_data.html can render it without also
    needing to import json.

    Also pulls document_intake_log.raw_aging_summary for the same
    statement_id -- a statement-level (not per-invoice) JSON blob of
    printed aging bucket totals, populated only for vendors whose
    extractor found one (see extract_wilberts.py's / extract_quirk.py's
    parse_aging_summary() and adapter.py's generic "aging_"-prefix
    pass-through). NULL/absent for every other vendor -- never merged
    into the per-invoice rows (INV-03).

    Returns a _RowsWithColumns: same list of row dicts as before, plus a
    `.columns` attribute -- the ordered union of every row's raw_columns
    keys (first-seen order), i.e. the real printed header names for this
    job's flat full-data table. Sourced from raw_ai_response when present
    (AI-routed vendors); falls back to the dedicated Bronze columns
    (charges/credits/amount_due/invoice_number/invoice_date/due_date/
    ro_number/po_number/work_order_number/description, plus Keystone's 4
    ledger columns) when it isn't (every python-library/pdfplumber
    vendor). Only genuinely empty if a job predates both -- a job run
    before raw_ai_response started being saved AND before this fallback
    existed; extracted_data.html's "not available" note is now that rare
    case, not the default for pdfplumber vendors. Also a `.aging_summary`
    attribute -- a dict, empty when this statement has none."""
    job = get_job_by_id(job_id)
    if not job or not job.get("statement_id"):
        return _RowsWithColumns([], [])
    statement_id = _resolve_bronze_statement_id(job)

    rows = execute_query(
        """
        SELECT
            raw_invoice_number AS invoice_number,
            raw_charges AS charges,
            raw_credits AS credits,
            raw_amount_due AS amount_due,
            raw_ai_response,
            raw_invoice_date, raw_due_date, raw_ro_number, raw_po_number,
            raw_work_order_number, raw_description,
            raw_balance_forward, raw_period_activity, raw_credit_applied, raw_payment_applied
        FROM bronze_vendor_statement_raw
        WHERE statement_id = ?
        ORDER BY page_number, row_number
        """,
        [statement_id],
    )

    columns = []
    seen = set()
    for row in rows:
        raw_response = row.get("raw_ai_response")
        try:
            raw_columns = json.loads(raw_response) if raw_response else None
        except (TypeError, ValueError):
            raw_columns = None
        row["raw_columns"] = raw_columns

        if raw_columns:
            for key in raw_columns.keys():
                if key not in seen:
                    seen.add(key)
                    columns.append(key)

    if not columns:
        # No row in this job has raw_ai_response (every python-library/
        # pdfplumber vendor, see get_extracted_rows_for_job()'s own
        # docstring) -- fall back to the dedicated Bronze columns
        # adapter.py's PythonLibraryExtractionEngine actually populates,
        # same table format as the AI-sourced one above, just built from
        # named columns instead of a JSON blob. A label is only added to
        # `columns` if at least one row has a real value for it, so e.g.
        # Keystone's 4 ledger columns don't show up as empty for every
        # other vendor.
        columns, seen = [], set()
        for row in rows:
            fallback = {
                "Invoice Number": row.get("invoice_number"),
                "Invoice Date": row.get("raw_invoice_date"),
                "Due Date": row.get("raw_due_date"),
                "Charges": row.get("charges"),
                "Credits": row.get("credits"),
                "Amount Due": row.get("amount_due"),
                "RO Number": row.get("raw_ro_number"),
                "PO Number": row.get("raw_po_number"),
                "Work Order Number": row.get("raw_work_order_number"),
                "Description": row.get("raw_description"),
                "Balance Forward": row.get("raw_balance_forward"),
                "Period Activity": row.get("raw_period_activity"),
                "Credit Applied": row.get("raw_credit_applied"),
                "Payment Applied": row.get("raw_payment_applied"),
            }
            row["raw_columns"] = fallback
            for key, value in fallback.items():
                if value is not None and key not in seen:
                    seen.add(key)
                    columns.append(key)

    intake_log_rows = execute_query(
        "SELECT raw_aging_summary FROM document_intake_log WHERE statement_id = ?",
        [statement_id],
    )
    aging_summary = None
    if intake_log_rows:
        raw_aging = intake_log_rows[0].get("raw_aging_summary")
        try:
            aging_summary = json.loads(raw_aging) if raw_aging else None
        except (TypeError, ValueError):
            aging_summary = None

    return _RowsWithColumns(rows, columns, aging_summary)


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

def _backfill_statement_periods(rows: list) -> list:
    """silver.recon_summary.statement_period is always NULL -- the
    Fabric-native Bronze/Silver the NetSuite matching flow reads
    (silver.statement) has no statement-level period field yet (see
    src/matching/fabric_matching.py:_fetch_statement()'s comment). The
    real value already exists on the local backend:
    document_intake_log.statement_period, extracted straight from the PDF
    at intake time (notebooks/01_document_intake.py), independent of
    which matching flow ran afterward. Batched by statement_id rather
    than one lookup per row -- same N+1 concern get_vendor_summaries()'s
    reason_breakdown batching documents, just against the cheaper local
    backend instead of Fabric."""
    missing_ids = [r["statement_id"] for r in rows if not r.get("statement_period")]
    if not missing_ids:
        return rows
    placeholders = ", ".join("?" for _ in missing_ids)
    intake_rows = execute_query(
        f"SELECT statement_id, statement_period FROM document_intake_log WHERE statement_id IN ({placeholders})",
        missing_ids,
    )
    period_by_statement = {
        r["statement_id"]: r["statement_period"] for r in intake_rows if r["statement_period"]
    }
    for row in rows:
        if not row.get("statement_period"):
            row["statement_period"] = period_by_statement.get(row["statement_id"])
    return rows


def get_all_runs() -> list:
    """Reads silver.recon_summary (Fabric Warehouse) -- the real NetSuite
    matching flow's output (src/matching/fabric_matching.py), same table
    get_recent_recon_runs() (Home page) and the Exceptions page already
    read. Trusts recon_summary's own stored matched_count/exception_count
    rather than re-deriving live counts per row, same reasoning as
    get_recent_recon_runs(). No is_latest_version filter here (unlike
    that function) -- Reports is meant to show every completed run, not
    just the current version per vendor+period."""
    rows = recon_query(
        """
        SELECT statement_id, vendor_name, statement_period, total_invoice_count,
               matched_count, exception_count, statement_total, overall_status,
               reconciliation_timestamp
        FROM silver.recon_summary
        ORDER BY reconciliation_timestamp DESC
        """
    )
    return _backfill_statement_periods(rows)


def get_statement_report(statement_id: str) -> dict:
    """summary/matched/exceptions now read silver.recon_matched_invoices/
    recon_summary/recon_exceptions (Fabric Warehouse) instead of the old
    gold_* tables -- see the recon_query import comment above. Three
    fields report_detail.html references -- summary.erp_version and
    matched/exceptions' charges/credits/amount_due -- don't exist in the
    recon_* schema (confirmed via live INFORMATION_SCHEMA.COLUMNS,
    2026-09-18). Unlike a SQL NULL, a genuinely absent dict key renders as
    Jinja's Undefined, which the template's `is not none` guards don't
    catch (Undefined is not None) -- feeding it into the `money` filter's
    float() raised UndefinedError instead of falling back to "—". Set
    explicitly to None below so the existing template guards work the
    same way they did against gold_*'s real (nullable) columns."""
    summary_rows = recon_query(
        "SELECT TOP 1 * FROM silver.recon_summary WHERE statement_id = ?",
        [statement_id],
    )
    summary = summary_rows[0] if summary_rows else None
    if summary is not None:
        summary.setdefault("erp_version", None)
        _backfill_statement_periods([summary])

    # TEMPORARY (2026-08-29): document_intake_log pointed back at Azure SQL
    # -- see get_vendor_name_for_statement()'s comment above for why.
    # Revert to execute_query_fabric() once the Fabric permission issue is
    # resolved. No trailing LIMIT here (harmless either way: write_intake_log()
    # DELETEs any existing row for this statement_id first, so there's at
    # most one anyway).
    intake_rows = execute_query(
        "SELECT * FROM document_intake_log WHERE statement_id = ?",
        [statement_id],
    )
    intake = intake_rows[0] if intake_rows else None
    if intake is not None:
        # shop_or_entity is stored as a JSON list (see write_intake_log());
        # the template just wants a display string, so join it here rather
        # than adding a new template filter for one field.
        try:
            shop_list = json.loads(intake["shop_or_entity"]) if intake.get("shop_or_entity") else []
        except (TypeError, ValueError):
            shop_list = []
        intake["shop_display"] = ", ".join(shop_list) if shop_list else None

    matched = recon_query(
        """
        SELECT invoice_number, ro_number, statement_amount, erp_amount, match_level
        FROM silver.recon_matched_invoices
        WHERE statement_id = ?
        ORDER BY invoice_number
        """,
        [statement_id],
    )
    for row in matched:
        row.setdefault("charges", None)
        row.setdefault("credits", None)
        row.setdefault("amount_due", None)

    exceptions = recon_query(
        """
        SELECT * FROM silver.recon_exceptions
        WHERE statement_id = ?
        ORDER BY exception_status, exception_reason, invoice_number
        """,
        [statement_id],
    )
    for row in exceptions:
        row.setdefault("charges", None)
        row.setdefault("credits", None)
        row.setdefault("amount_due", None)

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
    # TEMPORARY (2026-08-29): validation_document_review_queue pointed back
    # at Azure SQL via execute_query() -- the Fabric SQL Database item this
    # used to read (get_fabric_connection() in src/lakehouse/connection.py)
    # is unreachable in production right now (FABRIC_CLIENT_ID lacks Read
    # permission on it). Revert to execute_query_fabric() once that's
    # granted.
    #
    # Called from sidebar_context() on every page (see web/deps.py) --
    # still wrapped in a broad try/except (kept even after this swap) so
    # any transient DB connectivity failure here only degrades the
    # sidebar's nav-dot count to 0 instead of taking down every page in
    # the app.
    try:
        rows = execute_query(
            "SELECT COUNT(*) AS c FROM validation_document_review_queue WHERE review_status = 'PENDING_REVIEW'"
        )
        return rows[0]["c"] or 0 if rows else 0
    except Exception as e:
        print(f"[queries] get_pending_review_count failed, defaulting to 0: {e}")
        return 0


def get_review_queue_vendors() -> list:
    """One row per source_file with pending review rows, plus a
    rejection_category breakdown for that source_file's footer note.

    TEMPORARY (2026-08-29): validation_document_review_queue pointed back
    at Azure SQL -- see get_pending_review_count()'s comment above for why.
    Revert to execute_query_fabric() once the Fabric permission issue is
    resolved."""
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
    # TEMPORARY (2026-08-29): see get_pending_review_count()'s comment above.
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
    # TEMPORARY (2026-08-29): see get_pending_review_count()'s comment above.
    rows = execute_query(
        "SELECT * FROM validation_document_review_queue WHERE review_id = ?",
        [review_id],
    )
    return _parse_review_row(rows[0]) if rows else None


def action_review_item(review_id: str, action: str, reviewed_by: str) -> None:
    """Approves or flags a review queue row. Flagging also raises a
    recon_exceptions row (NOT gold_exceptions -- retargeted 2026-08-26
    alongside the rest of the exceptions page, see
    migrations/013_add_recon_tables.sql) so the item surfaces on the
    normal exceptions page too -- DUPLICATE_RECORD keeps its own reason so
    it reads distinctly from EXTRACTION_INCOMPLETE (every other
    rejection_category, e.g. MISSING_MANDATORY_FIELD, is genuinely an
    incomplete extraction).

    TEMPORARY (2026-08-29): the review-queue UPDATE below was
    execute_sql_fabric() (reading/writing if_vive_recon, the Fabric SQL
    Database item) -- see get_pending_review_count()'s comment for why
    it's pointed at Azure SQL via execute_sql() instead right now. Revert
    once the Fabric permission issue on if_vive_recon is resolved.

    The recon_exceptions INSERT and _recompute_summary_counts()'s
    silver.recon_summary update (both via recon_sql()) are untouched by
    that swap -- they target the Fabric Warehouse (if_vive_warehouse), a
    separate Fabric item from if_vive_recon with its own working
    credentials, unaffected by the SQLDB permission gap."""
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
        recon_sql(
            """
            INSERT INTO silver.recon_exceptions (
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
        # recon_summary row the same way a resolution can
        # overcount it — see _recompute_summary_counts()'s docstring. A
        # no-op if this statement_id has no summary row yet (the common
        # case: review-queue items are usually raised before a statement
        # ever reaches a full pipeline run).
        _recompute_summary_counts(item["statement_id"])


# ---------------------------------------------------------------------------
# Validation — Arithmetic Validation Gate (printed total vs. extracted sum)
# ---------------------------------------------------------------------------

def get_validation_report() -> list:
    """Every intake attempt's Arithmetic Validation Gate result
    (document_intake_log.validation_status/validation_difference --
    src/validation/arithmetic_gate.py). No is_latest_version scoping --
    shows every intake attempt ever logged, including superseded
    reprocessing of the same statement, per the user 2026-09-21.

    Pass/Fail is a strict binary: only validation_status == 'matches' is
    Pass. 'total_not_found' (no printed total on the PDF to compare
    against) counts as Fail here too, same as a genuine 'mismatch' --
    also per the user 2026-09-21."""
    rows = execute_query(
        """
        SELECT statement_id, source_file, vendor_name, statement_period,
               statement_total_as_printed, validation_status, validation_difference,
               ingestion_timestamp
        FROM document_intake_log
        WHERE validation_status IS NOT NULL
        ORDER BY ingestion_timestamp DESC
        """
    )
    for row in rows:
        row["passed"] = row["validation_status"] == "matches"
    return rows


def get_extraction_validation_detail(statement_id: str) -> dict:
    """Arithmetic-only detail for one intake attempt -- deliberately just
    the printed total, the extracted line items, and their sum, with NO
    reconciliation/NetSuite data (matched invoices, exceptions, ERP total).
    Separate from get_statement_report() (which is all reconciliation, no
    arithmetic-gate breakdown) per the user 2026-09-21: Validation checks
    that extraction itself is internally consistent (does the PDF's own
    printed total match what was actually extracted?), a question that's
    fully answered before matching ever runs, so recon data doesn't belong
    on this page.

    computed_total is derived as printed - validation_difference rather
    than re-summed here, so it's guaranteed to be the exact figure
    src/validation/arithmetic_gate.py computed at intake time (netting
    credits/reversals per its own docstring) -- naively re-summing
    silver.statement_line.charge_amount here would NOT reproduce that
    same figure in every case (credit-netting, dedup of matched reversal
    pairs) and would silently disagree with the pass/fail verdict shown.

    lines are for display only (line_number order, whatever silver.statement_line
    has for this statement_id) -- not re-summed against computed_total for
    the same reason."""
    intake_rows = execute_query(
        """
        SELECT statement_id, source_file, vendor_name, statement_period,
               statement_total_as_printed, validation_status, validation_difference,
               ingestion_timestamp
        FROM document_intake_log
        WHERE statement_id = ?
        """,
        [statement_id],
    )
    intake = intake_rows[0] if intake_rows else None
    if intake is None:
        return {"intake": None, "computed_total": None, "lines": []}

    intake["passed"] = intake["validation_status"] == "matches"
    printed = intake["statement_total_as_printed"]
    difference = intake["validation_difference"]
    computed_total = (
        round(printed - difference, 2)
        if printed is not None and difference is not None
        else None
    )

    lines = recon_query(
        """
        SELECT line_number, invoice_number, line_date, description_raw,
               charge_amount, payment_amount
        FROM silver.statement_line
        WHERE statement_id = ?
        ORDER BY line_number
        """,
        [statement_id],
    )

    return {
        "intake": intake,
        "computed_total": computed_total,
        "lines": lines,
    }
