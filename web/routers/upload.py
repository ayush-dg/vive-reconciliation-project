"""
upload.py

Accepts one or more vendor statement PDFs, saves each to sample_data/, and
queues a PENDING row per file in the jobs table — the background worker
(web/worker.py) picks these up and runs the existing pipeline as a
subprocess (extraction only for now — see run_full_pipeline.py's
--extract-only, matching is out of scope for the current build phase).
This router never touches pipeline internals directly, and never runs the
pipeline itself: it only enqueues work.

Every submission gets one batch_id (reusing the jobs.batch_id column that
web/routers/intake_trigger.py already stamps on Event-Grid deliveries — see
migrations/007_add_batch_id_to_jobs.sql), and POST /upload redirects to
/upload/status/{batch_id}, which polls until every file in the batch has
finished extracting and shows each one's detected vendor, statement period,
and extracted invoice rows.
"""

import os
import tempfile
import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from typing import List

from web.deps import render, require_login, sidebar_context
from web import queries
from src.ai.quick_preview import detect_vendor_and_period

router = APIRouter()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE_DATA_DIR = os.path.join(PROJECT_ROOT, "sample_data")


@router.get("/upload")
def upload_form(request: Request, user: str = Depends(require_login)):
    ctx = {
        "active_page": "upload",
        "error": None,
        "success": None,
        "recent_batches": queries.get_recent_upload_batches(),
        **sidebar_context(request),
    }
    return render(request, "upload.html", ctx)


@router.post("/upload/preview")
def upload_preview(request: Request, user: str = Depends(require_login),
                    file: UploadFile = File(...)):
    """Fast vendor/statement-period-only read of one PDF, called from the
    upload page the moment a file is picked (see web/static/app.js) — a
    live preview, not the real extraction. Writes to a throwaway temp
    file, never to sample_data/ (that only happens on a real POST /upload,
    once the user actually queues the file). Always returns 200 with
    best-effort (possibly null) fields — a preview failure must never
    block the user from queuing the file for the real extraction."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return {"vendor_name": None, "statement_period": None}

    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(file.file.read())
        return detect_vendor_and_period(tmp_path)
    except Exception:
        return {"vendor_name": None, "statement_period": None}
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@router.post("/upload")
def upload_submit(request: Request, user: str = Depends(require_login),
                   files: List[UploadFile] = File(...), period: str = Form(None),
                   notes: str = Form(None)):
    pdf_files = [f for f in files if f.filename and f.filename.lower().endswith(".pdf")]

    if not pdf_files:
        ctx = {
            "active_page": "upload",
            "error": "Only PDF files are accepted.",
            "success": None,
            **sidebar_context(request),
        }
        return render(request, "upload.html", ctx, status_code=400)

    os.makedirs(SAMPLE_DATA_DIR, exist_ok=True)
    batch_id = str(uuid.uuid4())

    for file in pdf_files:
        # Always save under the client's original filename — the pipeline
        # derives the vendor from the PDF's filename stem (see
        # derive_vendor_slug_from_filename / derive_vendor_name_from_filename
        # in notebooks/01_document_intake.py), so anything else breaks
        # vendor detection downstream. Normalize backslashes before
        # os.path.basename(), since on this (Linux) deployment it only
        # splits on "/" and a client sending a full Windows-style path
        # would otherwise leave it mostly intact.
        original_filename = file.filename.replace("\\", "/")
        safe_name = os.path.basename(original_filename)
        pdf_path = os.path.join(SAMPLE_DATA_DIR, safe_name)
        with open(pdf_path, "wb") as f:
            f.write(file.file.read())

        job_id = str(uuid.uuid4())
        queries.create_job(job_id=job_id, pdf_filename=safe_name, pdf_path=pdf_path,
                            submitted_by=user, batch_id=batch_id)

    return RedirectResponse(f"/upload/status/{batch_id}", status_code=303)


@router.get("/upload/status/{batch_id}")
def upload_status(batch_id: str, request: Request, user: str = Depends(require_login)):
    data = queries.get_upload_batch_status(batch_id)
    if not data["jobs"]:
        return RedirectResponse("/upload", status_code=303)

    jobs = data["jobs"]
    ctx = {
        "active_page": "upload",
        "batch_id": batch_id,
        "jobs": jobs,
        "completed_count": sum(1 for j in jobs if j["status"] == "COMPLETED"),
        "failed_count": sum(1 for j in jobs if j["status"] == "FAILED"),
        "active_count": sum(1 for j in jobs if j["status"] in ("PENDING", "PROCESSING")),
        **sidebar_context(request),
    }
    return render(request, "upload_status.html", ctx)


@router.get("/upload/status/{batch_id}/poll")
def upload_status_poll(batch_id: str, request: Request, user: str = Depends(require_login)):
    return queries.get_batch_job_statuses(batch_id)
