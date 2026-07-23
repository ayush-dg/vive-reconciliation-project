"""
exceptions.py

Exceptions vendors overview (/exceptions) and per-vendor review
(/exceptions/{vendor_name}). Actioning an exception writes a row to
exception_dispositions and marks the gold_exceptions row RESOLVED, then
redirects back to the same vendor so the next open exception is shown.
"""

from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from web.deps import render, require_login, sidebar_context
from web import queries

router = APIRouter()

REASON_BADGE = {
    "Invoice Missing": {"label": "Missing in ERP", "css": "danger"},
    "Amount Mismatch": {"label": "Amount mismatch", "css": "warning"},
    "EXTRACTION_INCOMPLETE": {"label": "Extraction incomplete", "css": "grey"},
    "DUPLICATE_RECORD": {"label": "Duplicate record", "css": "info"},
}


@router.get("/exceptions")
def exceptions_vendors(request: Request, user: str = Depends(require_login)):
    vendors = queries.get_vendor_summaries()
    for v in vendors:
        v["url_name"] = quote(v["vendor_name"] or "", safe="")

    vendors_with_ex = [v for v in vendors if v["exception_count"] > 0]
    total_open = sum(v["exception_count"] for v in vendors_with_ex)

    ctx = {
        "active_page": "exceptions",
        "vendors": vendors,
        "total_open": total_open,
        "vendor_count_with_ex": len(vendors_with_ex),
        "reason_badge": REASON_BADGE,
        **sidebar_context(request),
    }
    return render(request, "exceptions_vendors.html", ctx)


@router.get("/exceptions/{vendor_name:path}")
def exceptions_review(vendor_name: str, request: Request, user: str = Depends(require_login),
                       filter: str = "all", selected: str = None):
    vendor_name = unquote(vendor_name)
    statement = queries.get_vendor_latest_statement(vendor_name)

    # Vendors with OPEN gold_exceptions rows but no gold_reconciliation_summary
    # row at all (e.g. a flagged review-queue row raised before this
    # vendor's PDF got a full pipeline run — see queries.get_vendor_summaries())
    # have no statement to look up here; fall back to deriving one straight
    # from their gold_exceptions rows instead of 404ing.
    exceptions_only = False
    if not statement:
        statement = queries.get_exceptions_only_vendor(vendor_name)
        exceptions_only = statement is not None

    if not statement:
        ctx = {
            "active_page": "exceptions",
            "vendor_name": vendor_name,
            "not_found": True,
            **sidebar_context(request),
        }
        return render(request, "exceptions_review.html", ctx, status_code=404)

    if exceptions_only:
        source_file = statement["source_file"]
        open_list = queries.get_open_exceptions_for_source_file(source_file, None if filter == "all" else filter)
        total, resolved = queries.get_exception_counts_for_source_file(source_file)
    else:
        statement_id = statement["statement_id"]
        open_list = queries.get_open_exceptions(statement_id, None if filter == "all" else filter)
        total, resolved = queries.get_exception_counts(statement_id)

    selected_exc = None
    if selected:
        selected_exc = next((e for e in open_list if e["exception_id"] == selected), None)
    if not selected_exc and open_list:
        selected_exc = open_list[0]

    progress_pct = round((resolved / total) * 100) if total else 0

    ctx = {
        "active_page": "exceptions",
        "vendor_name": vendor_name,
        "vendor_url_name": quote(vendor_name, safe=""),
        "not_found": False,
        "statement": statement,
        "exceptions": open_list,
        "selected": selected_exc,
        "total": total,
        "resolved": resolved,
        "progress_pct": progress_pct,
        "filter": filter,
        "reason_badge": REASON_BADGE,
        **sidebar_context(request),
    }
    return render(request, "exceptions_review.html", ctx)


@router.post("/exceptions/{vendor_name:path}")
def exceptions_action(vendor_name: str, request: Request, user: str = Depends(require_login),
                       exception_id: str = Form(...), statement_id: str = Form(...),
                       invoice_number: str = Form(...), reason_code: str = Form(...),
                       action: str = Form(...), note: str = Form(""),
                       filter: str = Form("all")):
    vendor_name = unquote(vendor_name)
    queries.resolve_exception(
        exception_id=exception_id,
        statement_id=statement_id,
        vendor_name=vendor_name,
        invoice_number=invoice_number,
        reason_code=reason_code,
        disposition_status=action,
        notes=note or None,
        disposed_by=user,
    )
    suffix = f"?filter={filter}" if filter and filter != "all" else ""
    return RedirectResponse(f"/exceptions/{quote(vendor_name, safe='')}{suffix}", status_code=303)
