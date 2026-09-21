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
