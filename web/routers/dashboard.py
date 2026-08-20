"""
dashboard.py

Home page — KPI totals from gold_reconciliation_summary / gold_exceptions,
plus a table of recent reconciliation runs.
"""

from datetime import datetime

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
        # Deliberately not wired to queries.get_recent_runs() -- vendor-level
        # reconciliation summaries are hidden for this extraction-focused
        # demo phase (same intent as the Auto-reconciled/Open exceptions
        # KPI placeholders above), even though gold_reconciliation_summary
        # itself is still being populated normally by the matching engine.
        "runs": [],
        "recent_batches": queries.get_recent_completed_batches(limit=3),
        "dashboard_title": datetime.now().strftime("Dashboard — %B %Y"),
        "current_month_label": datetime.now().strftime("%b %Y"),
        **sidebar_context(request),
    }
    return render(request, "home.html", ctx)
