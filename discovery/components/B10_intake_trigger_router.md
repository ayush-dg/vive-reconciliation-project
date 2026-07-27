## B10 — intake_trigger router (Event Grid webhook)
ID: M-046
Layer: serving
Source file: web/routers/intake_trigger.py
Added: 2026-07-25 scoped BCE refresh (module built 2026-07-24, auth/container-pinning/rate-cap fix added 2026-07-25)

**Module** — intake_trigger router
**ID** — M-046
**Layer** — serving
**Primary Responsibility** — Azure Event Grid webhook endpoint for auto-intake from Blob Storage: when a PDF lands in the `incoming-statements` container of the `viverecondropzone` storage account, Event Grid POSTs here; each blob is downloaded to `sample_data/` and queued as a PENDING job, same as a manual upload (M-007), tagged `submitted_by="event-grid"` and a shared `batch_id` per delivery (see M-045).

**Inputs** — `POST /api/intake-trigger` — JSON body: either an Event Grid `SubscriptionValidationEvent` (one-time, on subscription creation) or a list/single object of `Microsoft.Storage.BlobCreated` events. Header `x-vive-webhook-secret` (see Error Behaviour — required as of 2026-07-25).

**Outputs**
- On the validation handshake: `{"validationResponse": <echoed validationCode>}`.
- On a batch of `BlobCreated` events: downloads each `.pdf` blob via `BlobStorageClient.download_pdf()`, writes it to `sample_data/`, and calls `queries.create_job()` once per successfully-downloaded PDF, all sharing one `batch_id` (a fresh UUID per request). Returns `{"status": "ok"}` regardless of how many individual blobs succeeded or failed — Event Grid's webhook schema has no per-event partial-failure signal.
- **No login is required** on this route (it is called by Azure Event Grid, not a signed-in user) — it is authenticated by shared secret instead (see Error Behaviour), not by `Depends(require_login)`.

**Public Interface**
- `intake_trigger(request) -> dict` — `POST /api/intake-trigger`
- `_is_authorized(request) -> bool` (private) — constant-time shared-secret check
- `_validation_response(events) -> dict | None` (private)
- `_blob_filename(blob_url) -> str` (private)
- `_intake_blob_created_event(event, batch_id) -> None` (private)
- Module constants: `WEBHOOK_SECRET_ENV_VAR = "VIVE_EVENTGRID_WEBHOOK_SECRET"`, `WEBHOOK_SECRET_HEADER = "x-vive-webhook-secret"`, `MAX_EVENTS_PER_REQUEST = 100`, `DROPZONE_CONTAINER = "incoming-statements"`, `DROPZONE_CONNECTION_STRING_ENV_VAR = "AZURE_BLOB_DROPZONE_CONNECTION_STRING"`

**Error Behaviour**
- **Authentication, added 2026-07-25 — was completely absent before this date.** `_is_authorized()` compares the `x-vive-webhook-secret` header against `VIVE_EVENTGRID_WEBHOOK_SECRET` via `hmac.compare_digest` (constant-time, avoids a timing side-channel), checked **before anything else runs**, including the validation handshake — a missing/wrong header, or an unconfigured secret, returns HTTP 401 and processes nothing. Fails closed: if the env var is unset, every request is rejected — there is no "auth disabled" fallback. Prior to this fix, the only check performed was echoing back the caller's own `validationCode`, which is a delivery-handshake formality (proves the endpoint can receive and reply to Event Grid's own initial subscription-creation POST), not authentication — anyone who found the URL could exercise it. See `discovery/RISK_REGISTER.md` R-009 for the full history; **the code fix is complete but not yet live** — `VIVE_EVENTGRID_WEBHOOK_SECRET` has not yet been generated or configured on the actual Azure Event Grid subscription (blocked on Azure permissions, pending Ashrith), so this route will fail-closed against any real Event Grid delivery until that infra step happens.
- **Event-count cap, added 2026-07-25 — no cap existed before.** `len(events) > MAX_EVENTS_PER_REQUEST` (100) → HTTP 413, checked after auth but before any blob processing. Bounds the cost of a single request; a legitimate Event Grid delivery is expected to stay well under this.
- **Per-event tolerance, unchanged from 2026-07-24's original build:** a non-PDF blob, or a blob whose download fails, is silently skipped (`_intake_blob_created_event()` returns early) rather than raising — one bad blob in a batch does not block the others, and the endpoint always returns `{"status": "ok"}` for any authorized, under-cap request regardless of individual blob outcomes.

**Known Fragility**
- **Container is now hard-pinned, but this required a companion fix in M-039, not just here.** This router constructs `BlobStorageClient(container_name=DROPZONE_CONTAINER, ...)` and passes through whatever `data.url` the request body claims — the actual container-pinning enforcement lives one layer down, in `BlobStorageClient.download_pdf()` (see M-039's rewritten contract). Before 2026-07-25, `download_pdf()` derived the container to download from directly out of that caller-supplied URL, ignoring the configured `container_name` entirely — this router's own `container_name=DROPZONE_CONTAINER` argument was silently dead for the download path. Fixed as of 2026-07-25; this router's code did not itself change for that fix, only its downstream dependency did — worth noting so a future reader doesn't assume this file alone is sufficient evidence the pinning holds.
- **`submitted_by="event-grid"` is hardcoded with no further attribution** — a job queued via a forged (but now correctly-authenticated, since the secret is presumably not leaked) request is indistinguishable in the `jobs` table from a genuine delivery. Acceptable given the shared-secret fix; would become a gap again if the secret were ever compromised.
- **`AZURE_BLOB_DROPZONE_CONNECTION_STRING`'s actual scope (which containers it can read) was not verified in this pass** — the container-pinning fix constrains what this *code path* will attempt to download, but if that connection string's underlying Azure-side permissions are broader than the single `incoming-statements` container, the pinning fix caps this application's own behavior, not the credential's blast radius if it were used directly against the Azure SDK outside this codebase. Out of scope for a code-only fix; worth an infra-side permissions review alongside the pending Event Grid subscription configuration.

**Change Impact** — `VIVE_EVENTGRID_WEBHOOK_SECRET` must be generated and configured as a static (secret) delivery header on the Event Grid subscription before any real delivery will be accepted — this is an infrastructure step, tracked as an open action item in `discovery/RISK_REGISTER.md` R-009, not a code change. Any future change to `download_pdf()`'s container-pinning logic (M-039) must be re-verified against this router's assumption that the download can never escape `DROPZONE_CONTAINER`.

**Callers** — none (top-level HTTP entry point, called by Azure Event Grid)
**Calls** — M-039 (`BlobStorageClient().download_pdf()`), M-011 (`create_job`)
**Integration Points Used** — IP-010 (Azure Event Grid webhook), IP-009-adjacent (Blob Storage, but a distinct dropzone storage account/connection string from IP-009's archival container)
