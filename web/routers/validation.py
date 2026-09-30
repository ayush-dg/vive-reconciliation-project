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
from web import time_window as tw
from src.vendor_identity import display_name as vendor_display_name

router = APIRouter()


@router.get("/validation")
def validation_list(request: Request, user: str = Depends(require_login)):
    runs = queries.get_validation_report()

    # "Last run" dropdown (2026-09-30) -- same Outlook-sync definitions as
    # Home/Exceptions (web/time_window.py's outlook_all_syncs()), applied
    # here to intake attempts instead of reconciliation runs. Entirely
    # client-side (this page never round-trips a range/sync param to the
    # server) -- each run gets the UTC ISO "value" (outlook_sync_options())
    # of whichever sync its own statement_id belongs to, or "" if none, so
    # the select's JS filter can do a plain string-equality match against
    # data-sync, same pattern as the existing vendor/shop/period filters.
    outlook_jobs = queries.get_outlook_synced_jobs()
    all_syncs = tw.outlook_all_syncs(outlook_jobs)
    sync_by_statement = {}
    for chain in all_syncs:
        sync_value = chain[0]["submitted_at"].isoformat() + "Z"
        for j in chain:
            if j.get("statement_id"):
                sync_by_statement[j["statement_id"]] = sync_value
    sync_options, sync_truncated = tw.outlook_sync_options(outlook_jobs)

    for run in runs:
        # Display-only casing normalization, same reasoning as
        # exceptions.py's exceptions_vendors() -- keeps the filter
        # dropdown options and each card's data-vendor/data-shop
        # attributes in sync with what's actually shown.
        run["vendor_display_name"] = smart_title(vendor_display_name(run.get("vendor_name")))
        run["shop"] = smart_title(run.get("shop"))
        run["sync_time"] = sync_by_statement.get(run.get("statement_id"), "")

    vendor_options = sorted({r["vendor_display_name"] for r in runs if r.get("vendor_display_name")})
    shop_options = sorted({r["shop"] for r in runs if r.get("shop")})
    # Newest first -- statement_period is "YYYY-MM" (see deps.period_label),
    # so a reverse string sort is a reverse date sort.
    period_options = sorted({r["statement_period"] for r in runs if r.get("statement_period")}, reverse=True)

    ctx = {
        "active_page": "validation",
        "runs": runs,
        "vendor_options": vendor_options,
        "shop_options": shop_options,
        "period_options": period_options,
        "sync_options": sync_options,
        "sync_truncated": sync_truncated,
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
