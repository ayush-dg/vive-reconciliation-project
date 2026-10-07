"""
function_app.py

HTTP-triggered Azure Function: pulls new PDF attachments from the shared
TARGET_MAILBOX (Outlook, via Microsoft Graph app-only auth) and writes
each one to the 'raw' container of this Function's own storage account
(MAILBOX_CONTAINER, same account as AzureWebJobsStorage -- see
requirements.txt/host.json neighbors and the app settings on
vive-mailbox-sync). Returns the list of newly-written blob paths; it does
not create reconciliation jobs itself -- see
web/routers/mailbox_sync.py, which calls this Function and then queues a
job per returned path (a job requires the PDF to exist on the *webapp's*
local disk, which this Function has no access to).

Blob layout:
raw/mailbox/{yyyy}/{mm}/{dd}/raw_statement/{uuid}__{filename}_{timestamp}.pdf
-- "mailbox" is this Function's SOURCE tag (a sibling "ui-upload" source
may exist later for manually-uploaded PDFs, written by different code
entirely); {yyyy}/{mm}/{dd} and the appended {timestamp} are both the
message's own receivedDateTime (see write_to_raw_zone), not the date this
Function happens to run. "raw_statement" is the pre-reconciliation stage
tag -- a later, separate pipeline step is expected to copy a statement
into a sibling "recon" stage folder once it's actually been reconciled;
this Function never writes there itself. Watermark state lives separately
at watermark/mailbox.json, deliberately outside the content tree, so
listing/deleting raw/mailbox/ content never needs to special-case a
bookkeeping file mixed in among it.

Idempotency: watermark/mailbox.json in the same container tracks the
receivedDateTime of the newest message this Function has finished
writing. Each run queries Graph for messages at or after that timestamp
and advances the watermark once per message, immediately after that
message's attachments are written -- not once at the end of the batch --
so a failure partway through a run only re-pulls the messages after the
failure point on the next run, never re-writes (and duplicates) ones
already done. A tie-break (processed_ids_at_last_timestamp) guards
against two messages sharing the exact same receivedDateTime: without it,
a `>` comparison against a watermark equal to both messages' timestamp
would silently skip whichever one wasn't processed first.

Triggers: the HTTP route (the web app's "Sync to Blob" button) and a
30-minute timer both run the same run_sync(). The timer is off unless
AUTO_SYNC_ENABLED=true, so deploying this code somewhere doesn't by itself
start polling that mailbox. After each timer pull it POSTs to the web
app's /mailbox-sync/auto (WEBAPP_AUTOSYNC_URL) so new PDFs get queued as
jobs without anyone clicking "Sync to Webapp" -- on every tick, not only
when this run found something, so PDFs the web app missed while it was
down or restarting still get picked up on the next tick.

Concurrency: run_sync() holds a blob lease on LOCK_BLOB_PATH for its whole
run. Without it a timer tick and a button click could overlap, both read
the same watermark, and write every new PDF twice. The lease is 60s and
renewed before each message, so a crashed run frees the lock on its own
within a minute instead of blocking every later run.
"""

import base64
import json
import logging
import os
import uuid
from datetime import datetime

import azure.functions as func
import msal
import requests
from azure.core.exceptions import HttpResponseError, ResourceExistsError
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp()

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
STORAGE_CONNECTION_ENV_VAR = "AzureWebJobsStorage"
MAILBOX_CONTAINER = os.environ.get("MAILBOX_CONTAINER", "raw")
WATERMARK_BLOB_PATH = os.environ.get("WATERMARK_BLOB_PATH", "watermark/mailbox.json")
LOCK_BLOB_PATH = os.environ.get("SYNC_LOCK_BLOB_PATH", "watermark/mailbox.lock")
LOCK_LEASE_SECONDS = 60

# Every 30 minutes, on the hour and half hour. A literal rather than a
# %APP_SETTING% reference: a missing app setting would stop the host from
# indexing the timer, which also takes the HTTP route down with it.
SYNC_SCHEDULE = "0 */30 * * * *"
AUTO_SYNC_ENABLED_ENV_VAR = "AUTO_SYNC_ENABLED"
WEBAPP_AUTOSYNC_URL_ENV_VAR = "WEBAPP_AUTOSYNC_URL"
AUTOSYNC_SECRET_ENV_VAR = "MAILBOX_AUTOSYNC_SECRET"
# Must match web/routers/mailbox_sync.py's AUTOSYNC_SECRET_HEADER.
AUTOSYNC_SECRET_HEADER = "x-vive-autosync-secret"

# This Function only ever handles the Outlook mailbox pull -- a future
# ui-upload source (manually-uploaded PDFs) would be written by entirely
# different code, not a config knob on this one, so this is a plain
# constant, not an env var.
SOURCE = "mailbox"

# No watermark file yet means this Function has never run against this
# mailbox before -- start from the beginning of time so the first run
# pulls everything currently sitting in the mailbox, rather than silently
# skipping a backlog that predates this feature.
EPOCH_WATERMARK = {"last_received_datetime": "1970-01-01T00:00:00Z", "processed_ids_at_last_timestamp": []}


def get_graph_token() -> str:
    """Acquires an app-only Graph access token via MSAL client-credentials
    flow. Raises RuntimeError on any auth failure -- there is no partial
    or cached-token fallback."""
    tenant_id = os.environ["AZURE_TENANT_ID"]
    client_id = os.environ["AZURE_CLIENT_ID"]
    client_secret = os.environ["AZURE_CLIENT_SECRET"]

    client = msal.ConfidentialClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )
    result = client.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"Graph auth failed: {result.get('error')}: {result.get('error_description')}")
    return result["access_token"]


def read_watermark(container_client) -> dict:
    """Reads watermark/mailbox.json; returns EPOCH_WATERMARK if it doesn't
    exist yet (first run)."""
    blob_client = container_client.get_blob_client(WATERMARK_BLOB_PATH)
    if not blob_client.exists():
        return dict(EPOCH_WATERMARK)
    return json.loads(blob_client.download_blob().readall())


def write_watermark(container_client, watermark: dict) -> None:
    container_client.get_blob_client(WATERMARK_BLOB_PATH).upload_blob(
        json.dumps(watermark), overwrite=True
    )


def advance_watermark(current: dict, message_id: str, message_received_at: str) -> dict:
    """Moves the watermark to message_received_at. If this message ties the
    current watermark's timestamp exactly, message_id is appended to the
    tie-break set instead of resetting it, so a later run can still tell
    which same-timestamp messages were already handled."""
    if message_received_at == current["last_received_datetime"]:
        tied_ids = current.get("processed_ids_at_last_timestamp", [])
        return {"last_received_datetime": message_received_at, "processed_ids_at_last_timestamp": tied_ids + [message_id]}
    return {"last_received_datetime": message_received_at, "processed_ids_at_last_timestamp": [message_id]}


def list_new_messages(token: str, watermark: dict) -> list:
    """Queries Graph for messages at or after the watermark's timestamp,
    oldest first, then drops any message already recorded as processed at
    that exact timestamp (see advance_watermark's tie-break note). Only
    messages with attachments are returned -- attachment-less messages
    have nothing for extract_pdf_attachments to do."""
    mailbox = os.environ["TARGET_MAILBOX"]
    headers = {"Authorization": f"Bearer {token}", "ConsistencyLevel": "eventual"}
    already_processed = set(watermark.get("processed_ids_at_last_timestamp", []))

    url = (
        f"{GRAPH_BASE}/users/{mailbox}/messages"
        f"?$filter=receivedDateTime ge {watermark['last_received_datetime']}"
        "&$select=id,subject,receivedDateTime,hasAttachments"
        "&$orderby=receivedDateTime asc"
        "&$top=50"
        "&$count=true"
    )

    messages = []
    while url:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        messages.extend(data.get("value", []))
        url = data.get("@odata.nextLink")

    return [m for m in messages if m.get("hasAttachments") and m["id"] not in already_processed]


def extract_pdf_attachments(token: str, message_id: str) -> list:
    """Returns [(filename, pdf_bytes), ...] for this message's PDF file
    attachments only. Unlike the original test script, this filters out
    non-PDF and inline (e.g. signature-logo image.png) attachments, and
    skips itemAttachments (forwarded emails, calendar invites) entirely --
    only '#microsoft.graph.fileAttachment' entries carry contentBytes.

    A PDF counts if EITHER its contentType is 'application/pdf' OR its
    filename ends in '.pdf' -- forwarding an email frequently mangles the
    original contentType into a generic 'application/octet-stream' (seen
    in ~11 of ~300 real statements in this mailbox, always on
    "Fw:"/"FW:"-prefixed messages), which would otherwise silently drop a
    genuine statement. contentType alone is trusted first since it's the
    more reliable signal when present and correct; the filename check is
    only a fallback for when contentType lies."""
    mailbox = os.environ["TARGET_MAILBOX"]
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/users/{mailbox}/messages/{message_id}/attachments"
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    pdfs = []
    for attachment in response.json().get("value", []):
        if attachment.get("@odata.type") != "#microsoft.graph.fileAttachment":
            continue
        name = attachment.get("name") or ""
        is_pdf = attachment.get("contentType") == "application/pdf" or name.lower().endswith(".pdf")
        if not is_pdf:
            continue
        content_bytes = attachment.get("contentBytes")
        if not content_bytes:
            continue
        pdfs.append((name or "statement.pdf", base64.b64decode(content_bytes)))
    return pdfs


def write_to_raw_zone(container_client, pdf_bytes: bytes, filename: str, received_at: str) -> str:
    """Writes one PDF to
    mailbox/{yyyy}/{mm}/{dd}/raw_statement/{uuid}__{filename}_{timestamp}.pdf
    inside the raw container (SOURCE == "mailbox"). Both the {yyyy}/{mm}/{dd}
    folder and the appended {timestamp} come from the message's own
    receivedDateTime -- not the date this Function happens to run -- so a
    backlog pulled in one run still lands under the correct historical
    dates instead of all bunching into whichever day the sync happened to
    execute.

    "raw_statement" is this Function's stage tag: this Function only ever
    writes the as-received PDF here, pre-reconciliation. A sibling "recon"
    stage folder (mailbox/{yyyy}/{mm}/{dd}/recon/...) is where a copy would
    land once a statement actually completes reconciliation -- that move
    is a separate, later pipeline step, not something this Function does.
    Returns the blob path (relative to the container) that was written."""
    received_dt = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
    safe_name = os.path.basename(filename.replace("\\", "/"))
    name_stem, ext = os.path.splitext(safe_name)
    timestamp = received_dt.strftime("%Y%m%dT%H%M%SZ")
    blob_path = (
        f"{SOURCE}/{received_dt:%Y}/{received_dt:%m}/{received_dt:%d}/raw_statement/"
        f"{uuid.uuid4()}__{name_stem}_{timestamp}{ext}"
    )
    container_client.get_blob_client(blob_path).upload_blob(pdf_bytes, overwrite=False)
    return blob_path


def acquire_sync_lock(container_client):
    """Returns a BlobLeaseClient holding LOCK_BLOB_PATH, or None if another
    run already holds it. Creates the (empty) lock blob on first use."""
    lock_blob = container_client.get_blob_client(LOCK_BLOB_PATH)
    if not lock_blob.exists():
        try:
            lock_blob.upload_blob(b"", overwrite=False)
        except ResourceExistsError:
            pass  # another run created it between exists() and here
    try:
        return lock_blob.acquire_lease(lease_duration=LOCK_LEASE_SECONDS)
    except HttpResponseError as e:
        if e.status_code == 409:
            return None
        raise


def release_sync_lock(lease) -> None:
    """Best-effort: if the lease already expired, there's nothing to free."""
    try:
        lease.release()
    except HttpResponseError:
        logging.warning("mailbox sync lock was already released or expired")


def pull_new_pdfs(container_client, lease) -> dict:
    """The Graph -> raw-zone pull itself. Caller must hold the sync lock;
    it is renewed before each message so a long backlog keeps it."""
    token = get_graph_token()
    watermark = read_watermark(container_client)
    messages = list_new_messages(token, watermark)

    new_blob_paths = []
    for message in messages:
        lease.renew()
        for filename, pdf_bytes in extract_pdf_attachments(token, message["id"]):
            new_blob_paths.append(
                write_to_raw_zone(container_client, pdf_bytes, filename, message["receivedDateTime"])
            )

        # Advanced per message, right after its attachments are written --
        # not once at the end of the loop -- so a failure on a later
        # message never re-triggers a re-pull (and duplicate write) of
        # messages already handled in this same run.
        watermark = advance_watermark(watermark, message["id"], message["receivedDateTime"])
        write_watermark(container_client, watermark)

    return {"new_blob_paths": new_blob_paths, "messages_processed": len(messages)}


def run_sync():
    """Shared by the HTTP route and the timer. Returns pull_new_pdfs()'s
    result, or None if another run holds the sync lock (nothing done)."""
    container_client = BlobServiceClient.from_connection_string(
        os.environ[STORAGE_CONNECTION_ENV_VAR]
    ).get_container_client(MAILBOX_CONTAINER)

    lease = acquire_sync_lock(container_client)
    if lease is None:
        return None
    try:
        return pull_new_pdfs(container_client, lease)
    finally:
        release_sync_lock(lease)


def notify_webapp() -> None:
    """Asks the web app to queue never-attempted mailbox PDFs as jobs.
    Never raises: the PDFs are already safe in blob storage, and the next
    tick (or the "Sync to Webapp" button) picks up anything this misses."""
    url = os.environ.get(WEBAPP_AUTOSYNC_URL_ENV_VAR)
    secret = os.environ.get(AUTOSYNC_SECRET_ENV_VAR)
    if not url or not secret:
        logging.warning("%s or %s not set -- web app not notified", WEBAPP_AUTOSYNC_URL_ENV_VAR, AUTOSYNC_SECRET_ENV_VAR)
        return
    try:
        response = requests.post(url, headers={AUTOSYNC_SECRET_HEADER: secret}, timeout=30)
        logging.info("web app auto-sync responded %s: %s", response.status_code, response.text[:200])
    except requests.RequestException as e:
        logging.warning("web app auto-sync call failed: %s", e)


@app.route(route="sync", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def sync(req: func.HttpRequest) -> func.HttpResponse:
    try:
        result = run_sync()
        if result is None:
            return func.HttpResponse(
                json.dumps({"error": "a mailbox sync is already running -- try again in a minute"}),
                mimetype="application/json",
                status_code=409,
            )
        return func.HttpResponse(json.dumps(result), mimetype="application/json", status_code=200)
    except Exception as e:
        logging.exception("mailbox sync failed")
        return func.HttpResponse(json.dumps({"error": str(e)}), mimetype="application/json", status_code=500)


@app.timer_trigger(schedule=SYNC_SCHEDULE, arg_name="timer", run_on_startup=False, use_monitor=True)
def scheduled_sync(timer: func.TimerRequest) -> None:
    if os.environ.get(AUTO_SYNC_ENABLED_ENV_VAR, "").lower() != "true":
        logging.info("%s is not 'true' -- scheduled mailbox sync skipped", AUTO_SYNC_ENABLED_ENV_VAR)
        return
    try:
        result = run_sync()
        if result is None:
            logging.info("scheduled mailbox sync skipped -- another sync holds the lock")
        else:
            logging.info("scheduled mailbox sync wrote %d PDF(s) from %d message(s)",
                         len(result["new_blob_paths"]), result["messages_processed"])
    finally:
        # Every tick, even after a failed or skipped pull -- the web app
        # may still have unqueued PDFs from an earlier run.
        notify_webapp()
