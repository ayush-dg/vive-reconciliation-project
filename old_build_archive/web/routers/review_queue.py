"""
review_queue.py

Review queue vendors overview (/review-queue) and per-source-file review
(/review-queue/{vendor_name}) for validation_document_review_queue --
rows an AP reviewer never sees today because intake only ever writes them
to that table (see notebooks/01_document_intake.py write_to_review_queue()),
never to gold_exceptions. Actioning a row either approves it in place or
flags it, which also raises a gold_exceptions row so it surfaces on the
normal exceptions page too (see queries.action_review_item()).

These rows have no AI-detected vendor_id/vendor_name, so source_file
stands in as the vendor grouping key -- the same quote()/unquote() URL
slug handling exceptions.py uses for vendor_name.
"""

from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from web.deps import render, require_login, sidebar_context
from web import queries

router = APIRouter()

CATEGORY_BADGE = {
    "MISSING_MANDATORY_FIELD": {"label": "Missing amount", "css": "warning"},
    "DUPLICATE_RECORD": {"label": "Duplicate", "css": "info"},
}


@router.get("/review-queue")
def review_queue_vendors(request: Request, user: str = Depends(require_login)):
    vendors = queries.get_review_queue_vendors()
    for v in vendors:
        v["url_name"] = quote(v["source_file"] or "", safe="")

    total_pending = sum(v["pending_count"] for v in vendors)

    ctx = {
        "active_page": "review_queue",
        "vendors": vendors,
        "total_pending": total_pending,
        "category_badge": CATEGORY_BADGE,
        **sidebar_context(request),
    }
    return render(request, "review_queue_vendors.html", ctx)


@router.get("/review-queue/{vendor_name:path}")
def review_queue_review(vendor_name: str, request: Request, user: str = Depends(require_login),
                         selected: str = None):
    vendor_name = unquote(vendor_name)
    items = queries.get_review_queue_for_vendor(vendor_name)

    selected_item = None
    if selected:
        selected_item = next((i for i in items if i["review_id"] == selected), None)
    if not selected_item and items:
        selected_item = items[0]

    ctx = {
        "active_page": "review_queue",
        "vendor_name": vendor_name,
        "vendor_url_name": quote(vendor_name, safe=""),
        "items": items,
        "selected": selected_item,
        "category_badge": CATEGORY_BADGE,
        **sidebar_context(request),
    }
    return render(request, "review_queue_review.html", ctx)


@router.post("/review-queue/{vendor_name:path}/action")
def review_queue_action(vendor_name: str, request: Request, user: str = Depends(require_login),
                         review_id: str = Form(...), action: str = Form(...)):
    vendor_name = unquote(vendor_name)
    queries.action_review_item(review_id=review_id, action=action, reviewed_by=user)
    return RedirectResponse(f"/review-queue/{quote(vendor_name, safe='')}", status_code=303)
