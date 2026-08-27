"""
reports.py

Reports list (all reconciliation runs) and a per-statement report detail
view built from gold_reconciliation_summary + gold_matched_invoices +
gold_exceptions.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from web.deps import render, require_login, sidebar_context
from web import queries

router = APIRouter()


@router.get("/reports")
def reports_list(request: Request, user: str = Depends(require_login)):
    ctx = {
        "active_page": "reports",
        "runs": queries.get_all_runs(),
        **sidebar_context(request),
    }
    return render(request, "reports.html", ctx)


@router.get("/reports/{statement_id}")
def report_detail(statement_id: str, request: Request, user: str = Depends(require_login)):
    data = queries.get_statement_report(statement_id)
    if not data["summary"]:
        return RedirectResponse("/reports", status_code=303)

    ctx = {
        "active_page": "reports",
        "statement_id": statement_id,
        **data,
        **sidebar_context(request),
    }
    return render(request, "report_detail.html", ctx)
