"""
validation.py

Validation report -- every intake attempt's Arithmetic Validation Gate
result (does the PDF's own printed total match the sum of its extracted
rows?), read-only. See web/queries.py::get_validation_report() and
src/validation/arithmetic_gate.py.
"""

from fastapi import APIRouter, Depends, Request

from web.deps import render, require_login, sidebar_context
from web import queries

router = APIRouter()


@router.get("/validation")
def validation_list(request: Request, user: str = Depends(require_login)):
    ctx = {
        "active_page": "validation",
        "runs": queries.get_validation_report(),
        **sidebar_context(request),
    }
    return render(request, "validation.html", ctx)


@router.get("/validation/{statement_id}")
def validation_detail(statement_id: str, request: Request, user: str = Depends(require_login)):
    # Deliberately separate from /reports/{statement_id} (report_detail.html)
    # -- this shows only the Arithmetic Validation Gate's own inputs
    # (printed total, extracted line items, extracted sum), no
    # reconciliation/NetSuite data. See get_extraction_validation_detail()'s
    # docstring.
    data = queries.get_extraction_validation_detail(statement_id)
    ctx = {
        "active_page": "validation",
        "statement_id": statement_id,
        **data,
        **sidebar_context(request),
    }
    return render(request, "validation_detail.html", ctx)
