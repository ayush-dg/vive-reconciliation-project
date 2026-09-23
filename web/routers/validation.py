"""
validation.py

Validation report -- every intake attempt's Arithmetic Validation Gate
result (does the PDF's own printed total match the sum of its extracted
rows?), read-only. See web/queries.py::get_validation_report() and
src/validation/arithmetic_gate.py.
"""

from fastapi import APIRouter, Depends, Request

from web.deps import render, require_login, sidebar_context, smart_title
from web import queries
from src.vendor_identity import display_name as vendor_display_name

router = APIRouter()


@router.get("/validation")
def validation_list(request: Request, user: str = Depends(require_login)):
    runs = queries.get_validation_report()
    for run in runs:
        # Display-only casing normalization, same reasoning as
        # exceptions.py's exceptions_vendors() -- keeps the filter
        # dropdown options and each card's data-vendor/data-shop
        # attributes in sync with what's actually shown.
        run["vendor_display_name"] = smart_title(vendor_display_name(run.get("vendor_name")))
        run["shop"] = smart_title(run.get("shop"))

    vendor_options = sorted({r["vendor_display_name"] for r in runs if r.get("vendor_display_name")})
    shop_options = sorted({r["shop"] for r in runs if r.get("shop")})

    ctx = {
        "active_page": "validation",
        "runs": runs,
        "vendor_options": vendor_options,
        "shop_options": shop_options,
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
