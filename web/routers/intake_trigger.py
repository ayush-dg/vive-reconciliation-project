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

No login is required on this route -- it is called by Azure Event Grid,
not a signed-in user.
"""

import os
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, Request

from src.storage.blob_client import BlobStorageClient
from web import queries

router = APIRouter()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE_DATA_DIR = os.path.join(PROJECT_ROOT, "sample_data")

DROPZONE_CONTAINER = "incoming-statements"
DROPZONE_CONNECTION_STRING_ENV_VAR = "AZURE_BLOB_DROPZONE_CONNECTION_STRING"

VALIDATION_EVENT_TYPE = "Microsoft.EventGrid.SubscriptionValidationEvent"
BLOB_CREATED_EVENT_TYPE = "Microsoft.Storage.BlobCreated"


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
    events = await request.json()
    if isinstance(events, dict):
        events = [events]

    validation_response = _validation_response(events)
    if validation_response is not None:
        return validation_response

    batch_id = str(uuid.uuid4())
    for event in events:
        _intake_blob_created_event(event, batch_id)

    return {"status": "ok"}
