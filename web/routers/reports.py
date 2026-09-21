"""
reports.py

Per-statement report detail view (matched invoices + exceptions +
Arithmetic Validation Gate) built from silver.recon_summary/
recon_matched_invoices/recon_exceptions + document_intake_log.

The list-of-all-runs page this used to have (GET /reports) was removed
2026-09-21 -- it duplicated the Exceptions vendor overview and Validation
page's own rollups, and had no working sidebar link even before removal
(see web/templates/base.html). GET /reports/{statement_id} survives
because it's the only place showing a statement's full matched-invoice
breakdown, not just its open exceptions or its Arithmetic Gate result --
reached now from the Validation page's "View" links instead of from the
removed list page.

GET /reports itself is kept as a bare placeholder -- home.html's "View
all reports" link (Reconciliation runs panel) still points here, and a
plain 404 there would be a broken-looking link rather than a deliberate
"this isn't built as its own page" message."""

from fastapi import APIRouter, Depends, Request

from web.deps import render, require_login, sidebar_context
from web import queries

router = APIRouter()


@router.get("/reports")
def reports_list(request: Request, user: str = Depends(require_login)):
    ctx = {
        "active_page": "validation",
        **sidebar_context(request),
    }
    return render(request, "reports.html", ctx)


@router.get("/reports/{statement_id}")
def report_detail(statement_id: str, request: Request, user: str = Depends(require_login)):
    data = queries.get_statement_report(statement_id)

    ctx = {
        "active_page": "validation",
        "statement_id": statement_id,
        **data,
        **sidebar_context(request),
    }
    return render(request, "report_detail.html", ctx)
