## B15 — Intake Trigger Router
ID: M-015
Layer: serving
Source file: `web/routers/intake_trigger.py`

**Module** — Intake Trigger Router
**ID** — M-015
**Layer** — serving
**Primary Responsibility** — Azure Event Grid webhook for auto-intake — downloads newly-arrived blobs from the drop-zone container and queues them as jobs, identically to a manual upload.

**Inputs** — Inbound `POST /api/intake-trigger` from Azure Event Grid (or a forged request, absent auth) — a JSON body of one or more events; `x-vive-webhook-secret` header.

**Outputs** — Downloaded PDFs written to `sample_data/`; one `jobs` row per blob via M-003's `create_job()`, tagged `submitted_by="event-grid"` and a shared `batch_id` per delivery.

**Public Interface** — `POST /api/intake-trigger` — no functions called by other modules. No login dependency (not user-facing).

**Error Behaviour**
- 401 if `_is_authorized()` fails (secret unset, or header mismatch via constant-time comparison) — checked before anything else in the handler.
- 413 if the event batch exceeds `MAX_EVENTS_PER_REQUEST` (100).
- A `SubscriptionValidationEvent` short-circuits to echo the validation code back, before any blob processing.
- Individual blob-download failures or non-PDF blobs are silently skipped (`_intake_blob_created_event()` returns early) — no per-event error surfaced back to Event Grid; a batch always returns `{"status": "ok"}` regardless of how many events were actually processed successfully.

**Known Fragility**
- **Fail-closed by design, not yet load-bearing in production** — `VIVE_EVENTGRID_WEBHOOK_SECRET` must be set for any request to succeed; per `TOPOLOGY.md`, the actual Event Grid subscription was not confirmed configured this session (blocked on Azure RBAC permissions per the archived record).
- Silent per-event skip on failure means a genuinely broken blob (corrupt download, wrong extension) produces no operator-visible signal beyond it simply never appearing as a queued job — indistinguishable from "Event Grid didn't send it" from this endpoint's perspective alone.

**Change Impact** — Shares `create_job()` (M-003) and the `sample_data/` write target with M-012 (upload router) — any change to job-creation semantics affects both intake paths identically.

**Callers** — IP-010 (Azure Event Grid, inbound — not another module in this codebase)
**Calls** — M-003 (`create_job`), M-043 (`BlobStorageClient.download_pdf`)
**Integration Points Used** — IP-010 (inbound), IP-009 (Azure Blob Storage, via M-043, different container/connection-string than the archival path)
