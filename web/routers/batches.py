"""
batches.py

Batch summary UI (see migrations/007_add_batch_id_to_jobs.sql and
web/routers/intake_trigger.py, which stamps a shared batch_id on every
job created from one Event Grid webhook delivery). /batches lists every
batch newest-first plus manually-uploaded jobs (batch_id = NULL) grouped
by date; /batches/{batch_id} is the per-file detail view for one batch.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from web.deps import render, require_login, sidebar_context
from web import queries

router = APIRouter()


@router.get("/batches")
def batches_list(request: Request, user: str = Depends(require_login)):
    ctx = {
        "active_page": "batches",
        "batches": queries.get_all_batches(),
        "manual_upload_groups": queries.get_manual_uploads(),
        **sidebar_context(request),
    }
    return render(request, "batches.html", ctx)


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: str, request: Request, user: str = Depends(require_login)):
    data = queries.get_batch_detail(batch_id)
    if not data["batch"]:
        return RedirectResponse("/batches", status_code=303)

    ctx = {
        "active_page": "batches",
        "batch": data["batch"],
        "jobs": data["jobs"],
        **sidebar_context(request),
    }
    return render(request, "batch_detail.html", ctx)
