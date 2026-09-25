"""
dashboard.py

Home page — KPI totals from gold_reconciliation_summary / gold_exceptions,
plus a table of recent reconciliation runs.
"""

from fastapi import APIRouter, Depends, Request

from web.deps import render, require_login, sidebar_context
from web import queries

router = APIRouter()


@router.get("/")
def home(request: Request, user: str = Depends(require_login)):
    ctx = {
        "active_page": "home",
        "kpis": queries.get_kpis(),
        "active_jobs": queries.get_active_jobs(),
        "failed_jobs": queries.get_failed_jobs(),
        # Re-enabled 2026-08-26 -- wired to the NEW NetSuite matching flow's
        # results (silver.recon_summary, Fabric), not
        # queries.get_recent_runs()'s gold_reconciliation_summary (a
        # different, voucher-based flow, still deliberately not shown here).
        "runs": queries.get_recent_recon_runs(limit=10),
        "recent_batches": queries.get_recent_completed_batches(limit=3),
        "netsuite_last_sync": queries.get_last_netsuite_sync(),
        "outlook_last_sync": queries.get_last_outlook_sync(),
        **sidebar_context(request),
    }
    return render(request, "home.html", ctx)
