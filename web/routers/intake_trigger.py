"""
intake_trigger.py

Azure Event Grid webhook for auto-intake from Blob Storage. When a PDF
lands in the 'incoming-statements' container of the 'viverecondropzone'
storage account, Event Grid POSTs here; each blob is downloaded to
sample_data/ and queued as a PENDING job, same as a manual upload (see
web/routers/upload.py).

Event Grid also POSTs a one-time SubscriptionValidationEvent when the
subscription is first created, which must be echoed back verbatim to
prove endpoint ownership -- see
https://learn.microsoft.com/azure/event-grid/webhook-event-delivery.
That echo is a delivery-handshake formality, not authentication -- it
proves nothing about who sent the request, since anyone can read
validationCode out of their own forged payload and echo it right back.

No login is required on this route -- it is called by Azure Event Grid,
not a signed-in user -- so it instead requires a shared secret configured
on the Event Grid subscription as a static delivery header (see
https://learn.microsoft.com/azure/event-grid/delivery-properties),
checked in _is_authorized() before anything else in the handler runs.
VIVE_EVENTGRID_WEBHOOK_SECRET must be set for any request to be accepted
-- there is deliberately no "unconfigured means open" fallback.
"""

import hmac
import os
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request

from src.storage.blob_client import BlobStorageClient
from web import queries

router = APIRouter()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE_DATA_DIR = os.path.join(PROJECT_ROOT, "sample_data")

DROPZONE_CONTAINER = "incoming-statements"
DROPZONE_CONNECTION_STRING_ENV_VAR = "AZURE_BLOB_DROPZONE_CONNECTION_STRING"

VALIDATION_EVENT_TYPE = "Microsoft.EventGrid.SubscriptionValidationEvent"
BLOB_CREATED_EVENT_TYPE = "Microsoft.Storage.BlobCreated"

WEBHOOK_SECRET_ENV_VAR = "VIVE_EVENTGRID_WEBHOOK_SECRET"
WEBHOOK_SECRET_HEADER = "x-vive-webhook-secret"

# Hard cap on events accepted per delivery -- Event Grid batches deliveries
# itself (typically well under this), so a legitimate delivery never gets
# near it; this exists solely to bound the cost of a single unauthenticated
# (or credential-leaked) request before auth/size checks, not to reflect
# any real expected batch size.
MAX_EVENTS_PER_REQUEST = 100


def _is_authorized(request: Request) -> bool:
    """Constant-time comparison of the configured shared secret against
    the caller-supplied header -- avoids leaking a timing side-channel on
    a byte-by-byte string compare. Returns False (never raises) if the
    secret isn't configured at all; that is a fail-closed misconfiguration,
    not an "auth disabled" mode."""
    configured_secret = os.environ.get(WEBHOOK_SECRET_ENV_VAR)
    if not configured_secret:
        return False
    supplied_secret = request.headers.get(WEBHOOK_SECRET_HEADER, "")
    return hmac.compare_digest(configured_secret, supplied_secret)


def _validation_response(events: list):
    """If this batch contains a SubscriptionValidationEvent, returns the
    {"validationResponse": ...} body Event Grid requires; else None."""
    for event in events:
        if event.get("eventType") == VALIDATION_EVENT_TYPE:
            return {"validationResponse": event.get("data", {}).get("validationCode")}
    return None


def _blob_filename(blob_url: str) -> str:
    return os.path.basename(urlparse(blob_url).path)


def _intake_blob_created_event(event: dict, batch_id: str) -> None:
    """Downloads one BlobCreated event's PDF into sample_data/ and queues
    a job for it. Non-PDF blobs and download failures are skipped --
    Event Grid has no per-event partial-failure signal in this webhook
    schema, so letting one bad blob raise would make the whole batch
    retry forever."""
    if event.get("eventType") != BLOB_CREATED_EVENT_TYPE:
        return

    blob_url = event.get("data", {}).get("url", "")
    filename = _blob_filename(blob_url)
    if not filename.lower().endswith(".pdf"):
        return

    os.makedirs(SAMPLE_DATA_DIR, exist_ok=True)
    dest_path = os.path.join(SAMPLE_DATA_DIR, filename)

    client = BlobStorageClient(
        container_name=DROPZONE_CONTAINER,
        connection_string_env_var=DROPZONE_CONNECTION_STRING_ENV_VAR,
    )
    if not client.download_pdf(blob_url, dest_path):
        return

    queries.create_job(
        job_id=str(uuid.uuid4()),
        pdf_filename=filename,
        pdf_path=dest_path,
        submitted_by="event-grid",
        batch_id=batch_id,
    )


@router.post("/api/intake-trigger")
async def intake_trigger(request: Request):
    if not _is_authorized(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    events = await request.json()
    if isinstance(events, dict):
        events = [events]

    if len(events) > MAX_EVENTS_PER_REQUEST:
        raise HTTPException(status_code=413, detail="Too many events in one delivery")

    validation_response = _validation_response(events)
    if validation_response is not None:
        return validation_response

    batch_id = str(uuid.uuid4())
    for event in events:
        _intake_blob_created_event(event, batch_id)

    return {"status": "ok"}
