"""
mailbox_sync.py

Two independent, login-gated buttons:

"Sync to Blob" calls the vive-mailbox-sync Azure Function (Graph pull +
write to the raw container's mailbox/ prefix + watermark advance -- see
azure-functions/mailbox-sync/function_app.py). It does nothing else --
it never downloads anything back or creates jobs. Its only job is "get
new PDFs out of Outlook and into blob storage."

"Sync to Webapp" is the other half, and doesn't talk to Outlook/the
Function at all. It lists what's already sitting in blob storage,
figures out what still needs to be downloaded and queued for extraction
(new arrivals, or previous failures under the retry cap), and queues
jobs for those -- same pattern as web/routers/upload.py and
web/routers/intake_trigger.py: a job only becomes real work once its PDF
exists on this app's own local disk (see web/worker.py's subprocess
call, which takes a local path, not a blob URL).

These two used to be one combined button. Splitting them means each
stage's failures are diagnosable on their own, and "Sync to Webapp" can
be retried without re-hitting Graph/Outlook unnecessarily.

Per-file tracking for "Sync to Webapp" lives entirely in each blob's own
metadata (extraction_status/attempt_count/last_error) -- not a separate
watermark file -- so a listing call can decide what needs downloading
without downloading anything first, and a file's fate never depends on
its position in some other file's history. web/worker.py is the other
half of this: it writes a job's outcome back onto its originating blob
(jobs.source_blob_path) once the job finishes.
"""

import os
import re
import threading
import uuid

import requests
from fastapi import APIRouter, Depends, Request

from src.storage.blob_client import BlobStorageClient
from web.deps import render, require_login, sidebar_context
from web import queries

router = APIRouter()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE_DATA_DIR = os.path.join(PROJECT_ROOT, "sample_data")

FUNCTION_URL_ENV_VAR = "MAILBOX_SYNC_FUNCTION_URL"
FUNCTION_KEY_ENV_VAR = "MAILBOX_SYNC_FUNCTION_KEY"
MAILBOX_CONNECTION_STRING_ENV_VAR = "AZURE_BLOB_MAILBOX_CONNECTION_STRING"
MAILBOX_CONTAINER = "raw"
MAILBOX_SOURCE_PREFIX = "mailbox/"

# After this many failed extraction attempts, "Sync to Webapp" stops
# auto-retrying a file -- it stays a normal FAILED job (visible, with its
# error, in /jobs/history), just no longer picked up automatically. This
# is the only thing that stops a permanently-broken PDF (corrupt file,
# unsupported layout) from silently re-running AI/OCR extraction forever
# on every single click.
RETRY_CAP = 10

# Two separate locks, not one -- these are now two independent
# operations. A "Sync to Blob" run in progress shouldn't block "Sync to
# Webapp" from running, or vice versa. Each is a non-blocking acquire: a
# second click while one is already running is told to try again rather
# than queuing behind it.
_blob_sync_lock = threading.Lock()
_webapp_sync_lock = threading.Lock()


@router.get("/mailbox-sync")
def mailbox_sync_form(request: Request, user: str = Depends(require_login)):
    ctx = {
        "active_page": "mailbox_sync",
        "blob_error": None,
        "blob_success": None,
        "webapp_error": None,
        "webapp_success": None,
        **sidebar_context(request),
    }
    return render(request, "mailbox_sync.html", ctx)


@router.post("/mailbox-sync/to-blob")
def sync_to_blob(request: Request, user: str = Depends(require_login)):
    ctx = {"active_page": "mailbox_sync", "webapp_error": None, "webapp_success": None, **sidebar_context(request)}

    if not _blob_sync_lock.acquire(blocking=False):
        ctx.update(blob_error="Sync to Blob already in progress -- try again shortly.", blob_success=None)
        return render(request, "mailbox_sync.html", ctx, status_code=409)

    try:
        new_blob_paths = _call_sync_function()
        count = len(new_blob_paths)
        ctx.update(
            blob_error=None,
            blob_success=f"{count} new PDF{'s' if count != 1 else ''} pulled from Outlook into blob storage.",
        )
        return render(request, "mailbox_sync.html", ctx)
    except Exception as e:
        ctx.update(blob_error=f"Sync to Blob failed: {e}", blob_success=None)
        return render(request, "mailbox_sync.html", ctx, status_code=502)
    finally:
        _blob_sync_lock.release()


@router.post("/mailbox-sync/to-webapp")
def sync_to_webapp(request: Request, user: str = Depends(require_login)):
    ctx = {"active_page": "mailbox_sync", "blob_error": None, "blob_success": None, **sidebar_context(request)}

    if not _webapp_sync_lock.acquire(blocking=False):
        ctx.update(webapp_error="Sync to Webapp already in progress -- try again shortly.", webapp_success=None)
        return render(request, "mailbox_sync.html", ctx, status_code=409)

    try:
        queued_names = _queue_eligible_blobs(submitted_by=user)
        count = len(queued_names)
        ctx.update(
            webapp_error=None,
            webapp_success=f"{count} PDF{'s' if count != 1 else ''} queued for extraction.",
        )
        return render(request, "mailbox_sync.html", ctx)
    except Exception as e:
        ctx.update(webapp_error=f"Sync to Webapp failed: {e}", webapp_success=None)
        return render(request, "mailbox_sync.html", ctx, status_code=502)
    finally:
        _webapp_sync_lock.release()


def _call_sync_function() -> list:
    """Calls the vive-mailbox-sync Function App and returns the list of
    newly-written blob paths (relative to the raw container) from its
    response. Raises on any non-2xx response or network failure -- the
    caller's except block turns that into the page's error message."""
    function_url = os.environ[FUNCTION_URL_ENV_VAR]
    function_key = os.environ[FUNCTION_KEY_ENV_VAR]
    response = requests.post(function_url, headers={"x-functions-key": function_key}, timeout=120)
    response.raise_for_status()
    return response.json().get("new_blob_paths", [])


# Strips the "{uuid}__" prefix and "_{timestamp}" suffix function_app.py's
# write_to_raw_zone adds around the original filename (e.g.
# "{uuid}__Statement_20260904T172231Z.pdf" -> "Statement.pdf"). Timestamp
# format is fixed (%Y%m%dT%H%M%SZ), so this is an exact match, not a guess.
_TIMESTAMP_SUFFIX_RE = re.compile(r"_\d{8}T\d{6}Z(\.[^.]*)$")


def _original_filename_from_blob_path(blob_path: str) -> str:
    """derive_vendor_slug_from_filename (notebooks/01_document_intake.py)
    keys off the saved file's basename to detect the vendor -- keeping the
    uuid prefix or timestamp suffix would break that detection, same
    reasoning as web/routers/upload.py's own note on this."""
    blob_basename = os.path.basename(blob_path)
    original_filename = blob_basename.split("__", 1)[1] if "__" in blob_basename else blob_basename
    return _TIMESTAMP_SUFFIX_RE.sub(r"\1", original_filename)


def _queue_eligible_blobs(submitted_by: str) -> list:
    """Lists every PDF blob under the mailbox source prefix (metadata
    included, no downloads yet), decides what's eligible using each
    blob's own extraction_status/attempt_count metadata -- never a
    separate watermark file -- claims each eligible one (an atomic,
    ETag-conditional metadata write, so two overlapping calls can't both
    claim the same blob), then downloads and queues a job for it.

    Eligible: no extraction_status yet (never attempted), or
    extraction_status=='failed' with attempt_count below RETRY_CAP.
    Skipped: extraction_status=='completed' (done), =='processing'
    (already in flight -- another run claimed it and hasn't finished),
    or =='failed' at/over RETRY_CAP (stays a normal FAILED job, visible
    in /jobs/history, just no longer auto-retried)."""
    client = BlobStorageClient(
        container_name=MAILBOX_CONTAINER,
        connection_string_env_var=MAILBOX_CONNECTION_STRING_ENV_VAR,
    )

    blob_map = client.get_blob_metadata_map(prefix=MAILBOX_SOURCE_PREFIX)

    queued_names = []
    for blob_path, info in blob_map.items():
        metadata = info["metadata"]
        etag = info["etag"]
        status = metadata.get("extraction_status")
        attempt_count = int(metadata.get("attempt_count", "0"))

        if status == "completed":
            continue
        if status == "processing":
            continue
        if status == "failed" and attempt_count >= RETRY_CAP:
            continue

        if not client.try_claim_blob_for_processing(blob_path, etag, metadata):
            continue  # lost the claim race (or metadata changed) -- next sync will re-evaluate it

        original_filename = _original_filename_from_blob_path(blob_path)
        upload_dir = os.path.join(SAMPLE_DATA_DIR, uuid.uuid4().hex[:8])
        os.makedirs(upload_dir, exist_ok=True)
        dest_path = os.path.join(upload_dir, original_filename)

        if not client.download_blob_by_name(blob_path, dest_path):
            # Already claimed as "processing" but never made it to a job --
            # mark it failed now (not left stuck at "processing" forever)
            # so the next sync can retry it, same as an extraction failure.
            client.set_blob_extraction_outcome(blob_path, "failed", last_error="Failed to download blob")
            continue

        queries.create_job(
            job_id=str(uuid.uuid4()),
            pdf_filename=original_filename,
            pdf_path=dest_path,
            submitted_by=submitted_by,
            source_blob_path=blob_path,
        )
        queued_names.append(original_filename)

    return queued_names
