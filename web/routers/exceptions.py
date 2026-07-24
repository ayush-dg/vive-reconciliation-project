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

# Bulk approve only ever targets exceptions the matching engine scored
# very high confidence — see queries.get_high_confidence_exception_count()
# and src/matching/engine.py's EXCEPTION_MATCH_CONFIDENCE. Deliberately
# the highest possible bar: today's highest-scoring exception type
# (Invoice Missing) tops out at 0.90, so at 0.99 nothing currently
# qualifies — that's intentional, not a bug; see
# get_high_confidence_exception_count()'s docstring.
BULK_APPROVE_THRESHOLD = 0.99


@router.get("/exceptions")
def exceptions_vendors(request: Request, user: str = Depends(require_login)):
    vendors = queries.get_vendor_summaries()
    for v in vendors:
        v["url_name"] = quote(v["vendor_name"] or "", safe="")
        v["aging"] = queries.get_exception_aging_summary(v["vendor_name"])

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
        "high_confidence_count": queries.get_high_confidence_exception_count(vendor_name, BULK_APPROVE_THRESHOLD),
        "bulk_approve_threshold": BULK_APPROVE_THRESHOLD,
        **sidebar_context(request),
    }
    return render(request, "exceptions_review.html", ctx)


@router.post("/exceptions/{vendor_name}/bulk-approve")
def exceptions_bulk_approve(vendor_name: str, request: Request, user: str = Depends(require_login),
                             threshold: float = BULK_APPROVE_THRESHOLD):
    """Approves every OPEN exception for this vendor with
    match_confidence >= threshold in one pass — see
    queries.bulk_approve_exceptions(). Registered ahead of the
    {vendor_name:path} POST action route below: Starlette's "path"
    converter matches greedily (regex .*), so if that route were checked
    first it would swallow "/bulk-approve" into vendor_name itself and
    this route would never be reached. A plain (non-":path") converter is
    safe here because every link to this route is built from
    quote(vendor_name, safe="") (see vendor_url_name below), which never
    leaves a literal "/" in the URL segment."""
    vendor_name = unquote(vendor_name)
    approved = queries.bulk_approve_exceptions(vendor_name, threshold, reviewed_by=user)
    return {"approved": approved}


@router.post("/exceptions/{vendor_name}/escalate")
def exceptions_escalate(vendor_name: str, request: Request, user: str = Depends(require_login),
                         exception_id: str = Form(...), filter: str = Form("all")):
    """Flags a single exception ESCALATED (see queries.escalate_exception())
    and redirects back to the same vendor/filter. Registered ahead of the
    {vendor_name:path} POST action route below for the same greedy-path-
    converter reason as exceptions_bulk_approve() above."""
    vendor_name = unquote(vendor_name)
    queries.escalate_exception(exception_id, escalated_by=user)
    suffix = f"?filter={filter}" if filter and filter != "all" else ""
    return RedirectResponse(f"/exceptions/{quote(vendor_name, safe='')}{suffix}", status_code=303)


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
