"""
upload.py

Accepts one or more vendor statement PDFs, saves each to sample_data/, and
queues a PENDING row per file in the jobs table — the background worker
(web/worker.py) picks these up and runs the existing pipeline as a
subprocess. This router never touches pipeline internals directly, and
never runs the pipeline itself: it only enqueues work and returns
immediately, per the "don't wait for processing" requirement.
"""

import os
import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from typing import List

from web.deps import render, require_login, sidebar_context
from web import queries

router = APIRouter()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE_DATA_DIR = os.path.join(PROJECT_ROOT, "sample_data")


@router.get("/upload")
def upload_form(request: Request, user: str = Depends(require_login)):
    ctx = {
        "active_page": "upload",
        "error": None,
        "success": None,
        **sidebar_context(request),
    }
    return render(request, "upload.html", ctx)


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
    queued_names = []

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

        # Each upload gets its own subdirectory (named by a short uuid) so
        # re-uploading the same filename can never overwrite an
        # already-queued job's file out from under it. The saved file's
        # basename stays exactly safe_name (not prefixed/renamed) --
        # derive_vendor_slug_from_filename/derive_vendor_name_from_filename
        # in notebooks/01_document_intake.py key off os.path.basename(pdf_path),
        # so anything else breaks vendor detection downstream (see this
        # file's own earlier comment on that).
        upload_dir = os.path.join(SAMPLE_DATA_DIR, uuid.uuid4().hex[:8])
        os.makedirs(upload_dir, exist_ok=True)
        pdf_path = os.path.join(upload_dir, safe_name)
        with open(pdf_path, "wb") as f:
            f.write(file.file.read())

        job_id = str(uuid.uuid4())
        queries.create_job(job_id=job_id, pdf_filename=safe_name, pdf_path=pdf_path, submitted_by=user)
        queued_names.append(safe_name)

    count = len(queued_names)
    ctx = {
        "active_page": "upload",
        "error": None,
        "success": f"{count} file{'s' if count != 1 else ''} queued for processing.",
        **sidebar_context(request),
    }
    return render(request, "upload.html", ctx)
