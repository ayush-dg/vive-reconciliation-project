"""
mailbox_sync.py

Login-gated "Sync Outlook Now" button. Calls the vive-mailbox-sync Azure
Function (Graph pull + write to the raw container's mailbox/ prefix +
watermark advance -- see azure-functions/mailbox-sync/function_app.py),
then downloads each newly-written PDF into sample_data/ and queues a job
per file, same pattern as web/routers/upload.py and
web/routers/intake_trigger.py -- a job only becomes real work once its
PDF exists on this app's own local disk (see web/worker.py's subprocess
call, which takes a local path, not a blob URL).

The Function only ever writes brand-new blobs and returns their paths; it
never creates jobs itself, since it has no access to this app's disk.
This route is therefore the only place that turns a mailbox pull into
actual reconciliation work.
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

# TEMPORARY -- remove after testing. Skips queuing jobs for the large 09-04
# backlog so a local test run only has to deal with the ~23 PDFs from other
# days, not the full ~300-PDF batch. Does not affect the Outlook pull or
# blob archival -- 09-04 PDFs still land in blob storage, just unqueued.
# Matches on the filename's timestamp suffix (_20260904T...) rather than a
# folder prefix, since raw/outlook/{yyyy}/{mm}/... no longer has a
# day-level folder -- the day now lives only in that suffix.
_TEMP_SKIP_DATE_MARKER = "_20260904T"

# Guards against two overlapping runs (e.g. a double-click, or two people
# clicking at once) both reading the same watermark and double-queuing
# the same messages. A non-blocking acquire: a second request while one
# run is in flight is told to try again rather than queuing behind it.
_sync_lock = threading.Lock()


@router.get("/mailbox-sync")
def mailbox_sync_form(request: Request, user: str = Depends(require_login)):
    ctx = {
        "active_page": "mailbox_sync",
        "error": None,
        "success": None,
        **sidebar_context(request),
    }
    return render(request, "mailbox_sync.html", ctx)


@router.post("/mailbox-sync")
def mailbox_sync_run(request: Request, user: str = Depends(require_login)):
    if not _sync_lock.acquire(blocking=False):
        ctx = {
            "active_page": "mailbox_sync",
            "error": "Sync already in progress -- try again shortly.",
            "success": None,
            **sidebar_context(request),
        }
        return render(request, "mailbox_sync.html", ctx, status_code=409)

    try:
        new_blob_paths = _call_sync_function()
        queued_names = _queue_jobs_for_blobs(new_blob_paths, submitted_by=user)
        count = len(queued_names)
        ctx = {
            "active_page": "mailbox_sync",
            "error": None,
            "success": f"{count} new PDF{'s' if count != 1 else ''} pulled and queued for extraction.",
            **sidebar_context(request),
        }
        return render(request, "mailbox_sync.html", ctx)
    except Exception as e:
        ctx = {
            "active_page": "mailbox_sync",
            "error": f"Sync failed: {e}",
            "success": None,
            **sidebar_context(request),
        }
        return render(request, "mailbox_sync.html", ctx, status_code=502)
    finally:
        _sync_lock.release()


def _call_sync_function() -> list:
    """Calls the vive-mailbox-sync Function App and returns the list of
    newly-written blob paths (relative to the mailbox container) from its
    response. Raises on any non-2xx response or network failure -- the
    caller's except block turns that into the page's error message."""
    function_url = os.environ[FUNCTION_URL_ENV_VAR]
    function_key = os.environ[FUNCTION_KEY_ENV_VAR]
    response = requests.post(function_url, headers={"x-functions-key": function_key}, timeout=120)
    response.raise_for_status()
    return response.json().get("new_blob_paths", [])


# Strips the "_{timestamp}" suffix function_app.py's write_to_raw_zone appends
# just before the extension (e.g. "Statement_20260904T172231Z.pdf" ->
# "Statement.pdf"). Timestamp format is fixed (%Y%m%dT%H%M%SZ), so this is an
# exact match, not a guess.
_TIMESTAMP_SUFFIX_RE = re.compile(r"_\d{8}T\d{6}Z(\.[^.]*)$")


def _queue_jobs_for_blobs(blob_paths: list, submitted_by: str) -> list:
    """Downloads each newly-landed blob into its own sample_data/ subdirectory
    and queues a job for it -- same pattern as
    web/routers/intake_trigger.py's Event Grid path. blob_path's basename is
    '{uuid}__{original_filename}_{timestamp}.pdf' (see function_app.py's
    write_to_raw_zone); both the uuid prefix and the timestamp suffix are
    stripped before saving locally, since derive_vendor_slug_from_filename
    (notebooks/01_document_intake.py) keys off the saved file's basename to
    detect the vendor -- keeping either would break that detection, same
    reasoning as web/routers/upload.py's own note on this."""
    if not blob_paths:
        return []

    client = BlobStorageClient(
        container_name=MAILBOX_CONTAINER,
        connection_string_env_var=MAILBOX_CONNECTION_STRING_ENV_VAR,
    )

    queued_names = []
    for blob_path in blob_paths:
        if _TEMP_SKIP_DATE_MARKER in blob_path:
            continue  # TEMPORARY -- remove after testing (skips the 09-04 backlog for now)

        blob_basename = os.path.basename(blob_path)
        original_filename = blob_basename.split("__", 1)[1] if "__" in blob_basename else blob_basename
        original_filename = _TIMESTAMP_SUFFIX_RE.sub(r"\1", original_filename)

        upload_dir = os.path.join(SAMPLE_DATA_DIR, uuid.uuid4().hex[:8])
        os.makedirs(upload_dir, exist_ok=True)
        dest_path = os.path.join(upload_dir, original_filename)

        if not client.download_blob_by_name(blob_path, dest_path):
            continue  # already logged by blob_client; skip queuing a job for a file we couldn't fetch

        queries.create_job(
            job_id=str(uuid.uuid4()),
            pdf_filename=original_filename,
            pdf_path=dest_path,
            submitted_by=submitted_by,
        )
        queued_names.append(original_filename)

    return queued_names
