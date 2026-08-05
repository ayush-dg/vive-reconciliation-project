# INTEGRATION_CONTRACTS.md — VIVE Reconciliation
Produced by: BCE Stage 2 Session E, Part 1 (CC, per Path A precedent — human review gate is the enforcement mechanism) — fresh extraction
Date: 2026-08-05

Synthesized from `discovery/TOPOLOGY.md` A03, `discovery/MODULE_CONTRACTS.md`, and `discovery/INVARIANT_CATALOGUE.md` — no new source reads performed, per the methodology's own instruction for this session. One record per IP-NNN assigned in Session A.

---

## IP-001 — Claude Sonnet 4.6 (Azure AI Foundry)

**Called by:** M-025

**What the application promises to send:** The whole PDF as one base64-encoded document content block, plus the client's own internal `EXTRACTION_PROMPT` (not the caller-supplied `prompt` argument — see IC-11/RULE-07's note that this client ignores the passed prompt), via a streaming Messages API call.

**What the application assumes it will receive:** A JSON object shaped `{vendor_name, statement_date, columns_found, rows: [{...cols, confidence}]}`, with a genuine per-row `confidence` field the model is explicitly asked to calibrate (IC-01's upstream data source).

**Auth mechanism:** API key (`AZURE_CLAUDE_API_KEY`) routed through an Azure Foundry endpoint (`AZURE_CLAUDE_ENDPOINT`), via `anthropic.AnthropicFoundry`.

**Error handling assumptions:** Never allowed to raise past this client — any failure (auth, timeout, malformed response, detected truncation) becomes a clean `AIResponse(success=False)`, and the caller (M-024) falls through to the deterministic fallback (M-031) unconditionally.

**Known divergences:** None — confirmed this session that the model reliably returns the promised shape and a genuine confidence signal (RULE-04's corrected 2026-07-24 entry, independently re-verified against current source).

**Gaps:** Streaming is required specifically because a non-streaming call on a long whole-document extraction risks tripping a read timeout — this is a real operational dependency on Anthropic's streaming API remaining available/performant, not backstopped by any fallback within this client itself (a streaming-specific outage would present as a generic failure and fall through to M-031, same as any other failure — no distinct handling for "streaming broke" vs. "the model errored").

---

## IP-002 — Claude Haiku 4.5 (Azure AI Foundry)

**Called by:** M-026 (instantiated via M-023's `get_ai_client("claude")`, used only by M-033)

**What the application promises to send:** A text-only prompt (`EXPLANATION_PROMPT_TEMPLATE`, filled with one exception's details) via a plain Messages API call — no document/file content.

**What the application assumes it will receive:** A JSON object with `probable_cause`, `suggested_resolution`, `confidence_score`, `business_impact`.

**Auth mechanism:** API key (`AZURE_CLAUDE_API_KEY`, same variable as IP-001 but a different deployment env var) routed through Azure Foundry.

**Error handling assumptions:** Never raises; a failure is caught by M-033's `_explain_one()`, counted as `failed`, and the loop continues to the next exception — a partial-batch failure never blocks the rest.

**Known divergences:** None found.

**Gaps:** This provider choice is hardcoded independently of `active_provider.json` — if the extraction chain's primary provider is ever migrated off Anthropic entirely, this explanation path would not follow automatically and nobody would be alerted, since the two are deliberately decoupled by design.

---

## IP-003 — Azure OpenAI (gpt-5-mini / gpt-5-nano / gpt-5.1, Responses API)

**Called by:** M-027 (dormant — reachable only via an explicit `get_ai_client("azure_gpt5_*")` call; no current caller reaches it)

**What the application promises to send:** One Responses API call per PDF page — text-layer pages as an inline base64 `input_file` block, scanned (no-text-layer) pages rasterized locally and sent as `input_image` instead. `temperature` is never actually forwarded despite being accepted as a parameter (these reasoning models reject it outright).

**What the application assumes it will receive:** Per-page JSON matching the Universal Financial Document Schema shape, aggregated by the client into one document-level result; a `status == "incomplete"` response is treated as a distinct failure mode (token budget exhausted on internal reasoning) rather than an empty success.

**Auth mechanism:** API key + endpoint + deployment name env vars.

**Error handling assumptions:** Never raises; each page retries once before being recorded as a failed page — one bad page doesn't abort the document.

**Known divergences:** None — dormant, no live traffic to diverge from expectation.

**Gaps:** Not exercised by any current traffic — its retry/truncation-salvage logic has no production signal confirming it still works correctly against whatever version of the Responses API is live today; a real activation would need to re-validate this before trusting it in production.

---

## IP-004 — Azure Document Intelligence (`prebuilt-layout`)

**Called by:** M-028 (dormant — reachable only via an explicit `get_ai_client("azure_doc_intel")` call)

**What the application promises to send:** The whole PDF in one `begin_analyze_document()` call using the `prebuilt-layout` model (not `prebuilt-invoice` — deliberately, since the real documents are statements with many invoices per page, not one invoice per document).

**What the application assumes it will receive:** Generic table geometry (rows/cells, no semantic field labels), mapped into schema fields by reusing M-031's shared column-header interpreter.

**Auth mechanism:** API key + endpoint env vars.

**Error handling assumptions:** Never raises; retries once on the whole-document call; a continuation table whose column count doesn't match the last detected header is skipped with a warning rather than risking a misaligned mapping.

**Known divergences:** None found.

**Gaps:** The continuation-table reuse logic is tuned to one confirmed real case (one logical table split across pages with a header only on page 1) — a vendor with a genuinely different multi-table-same-column-count layout would be mis-handled, with no way to distinguish the two cases from column count alone (see G03/C13's Known Fragility).

---

## IP-005 — Google Gemini 2.5 Flash (google-genai SDK)

**Called by:** M-029 (dormant — reachable only via an explicit `get_ai_client("gemini")` call)

**What the application promises to send:** The whole PDF as one Files API upload, followed by one `generate_content` call with `EXTRACTION_PROMPT`.

**What the application assumes it will receive:** A JSON object shaped `{vendor_name, statement_date, columns_found, rows}` — **without** a per-row confidence field (this client's prompt, unlike M-025's, does not ask for one; every row gets a fixed `ROW_CONFIDENCE = 0.75`).

**Auth mechanism:** API key (`GEMINI_API_KEY`).

**Error handling assumptions:** Never raises; specifically retries on a 503 UNAVAILABLE response (up to `max_retries`, 60s wait) — any other error fails immediately with no retry.

**Known divergences:** **Confirmed, carried forward from the archived record:** no totals/summary-row filter exists at either prompt or code level for this client (archived R-002) — re-confirmed still true this session, this client remains dormant so the exposure is real but currently unreachable by live traffic.

**Gaps:** Same flat-`0.75`-confidence gap as R-001 originally described — dormant, so no live risk today, but a real regression waiting if this provider is ever reactivated without first porting M-025's fix.

---

## IP-006 — Mistral Medium (direct Mistral API)

**Called by:** M-030 (dormant — reachable only via an explicit `get_ai_client("mistral")` call)

**What the application promises to send:** Every page rasterized to PNG (Mistral rejects raw PDF data URIs outright) and sent as one chat-completions call per page image.

**What the application assumes it will receive:** Per-page JSON with both a raw column-keyed dict and a mapped standard-fields dict; the raw dict is stashed into `description` as JSON (explicitly marked TEMPORARY in the source).

**Auth mechanism:** API key + endpoint + deployment env vars.

**Error handling assumptions:** Never raises; per-page retry-once-then-record-failure, same shape as IP-003.

**Known divergences:** Same as IP-005 — no totals-row filter, no genuine per-row confidence (fixed `0.75`), dormant so no live exposure.

**Gaps:** This client's prompt deliberately omits the confidence/metadata request entirely (diagnostic testing found the model's self-reported confidence and row counts unreliable) — a design choice specific to this provider, not an oversight, but it means even a future "port the confidence fix" effort for M-029/M-030 can't simply copy M-025's prompt pattern; the underlying signal quality issue for this specific provider was never solved, only worked around by not asking.

---

## IP-007 — Tesseract OCR + Poppler (local binaries)

**Called by:** M-032, called by M-031

**What the application promises to send:** Nothing over a network — a local binary invocation (`pytesseract`/`pdf2image`), one page rasterized and OCR'd at a time.

**What the application assumes it will receive:** Raw OCR text for the page, converted by M-031 into a pseudo-table for the shared column-mapping logic.

**Auth mechanism:** None — local binary, no network auth.

**Error handling assumptions:** `is_ocr_available()` never raises, returning `False` on any missing dependency or unreachable binary; the caller (M-031) treats unavailability as a normal, handled case.

**Known divergences:** None — this is a local, deterministic path with no external contract to diverge from.

**Gaps:** `_configure_tesseract_path()` hardcodes a Windows-specific default install path as its only fallback when `tesseract` isn't already on `PATH` — a non-Windows deployment or non-default install location silently degrades to "OCR unavailable" with no diagnostic pointing at the actual cause (wrong hardcoded path assumption).

---

## IP-008 — Azure SQL / SQLite (lakehouse database)

**Called by:** M-003, M-016, M-017, M-020, M-034, M-035, M-039, M-040 (all via M-037)

**What the application promises to send:** Parameterized SQL (via `?` placeholders, pyodbc's default paramstyle on both backends) — never raw string-interpolated values; two SQLite-specific constructs (`INSERT OR REPLACE`, trailing `LIMIT`) are rewritten to T-SQL equivalents before reaching the driver.

**What the application assumes it will receive:** Rows as list-of-dict results (`execute_query()`) or a cursor (`execute_sql()`) — backend-agnostic from the caller's perspective, by design.

**Auth mechanism:** Azure SQL — username/password via pyodbc connection string, TLS encrypted. SQLite — none (local file).

**Error handling assumptions:** Azure SQL connection drops (SQLSTATE 08S01/08001, from serverless auto-pause) are retried up to 3 times with a fresh connection; any other error propagates immediately, unretried.

**Known divergences:** None for this path specifically — the dialect translation is confirmed narrow-but-correct for the two patterns this codebase actually uses.

**Gaps:** `_translate_for_azure()` is explicitly not a general-purpose SQL dialect translator — any new SQLite-only syntax introduced elsewhere that isn't one of the two known patterns would fail differently (and possibly silently-wrong, not just loudly-erroring) on Azure SQL than on SQLite, with nothing to catch the mismatch before it reaches the driver.

---

## IP-009 — Azure Blob Storage (`vendor-statements` container)

**Called by:** M-043, called by M-017 (archival) and M-015 (drop-zone download, different container/connection-string)

**What the application promises to send:** One blob upload per PDF, keyed `{vendor_slug}/{yyyy}/{mm}/{document_hash}.pdf`, with `original_filename`/`vendor_name`/`uploaded_by` metadata attached.

**What the application assumes it will receive:** A blob URL on successful upload; on download, the raw PDF bytes for a caller-supplied blob URL, with the container segment of that URL verified (not trusted) against the configured container before any read is attempted.

**Auth mechanism:** Connection string (`AZURE_BLOB_CONNECTION_STRING` for archival; `AZURE_BLOB_DROPZONE_CONNECTION_STRING` for the drop-zone path, per-caller).

**Error handling assumptions:** Never raises from either public method — missing config, missing file, or any SDK/network failure all return `None`/`False`; every caller logs a warning and continues, since archival/download are explicitly non-blocking for the pipeline.

**Known divergences:** None — confirmed the container-pinning fix (archived R-009) remains in place this session.

**Gaps:** A silent archival failure (connection string unset, network blip) means a statement's source PDF is never actually archived, with no retry and no alert beyond a printed warning — the only signal is absence, which nothing currently monitors for.

---

## IP-010 — Azure Event Grid (auto-intake webhook)

**Called by:** M-015 (inbound HTTP POST, not called by this codebase — Event Grid calls in)

**What the application promises to send:** A `{"validationResponse": ...}` echo on the one-time subscription validation handshake; otherwise `{"status": "ok"}` regardless of how many individual blob events actually succeeded or were skipped within the batch.

**What the application assumes it will receive:** A JSON array (or single object) of Event Grid events, each either a `SubscriptionValidationEvent` or a `Microsoft.Storage.BlobCreated` event with a `data.url` field; a shared secret in the `x-vive-webhook-secret` header on every real delivery.

**Auth mechanism:** Shared secret (`VIVE_EVENTGRID_WEBHOOK_SECRET`), constant-time-compared against the header — fails closed (401) if the secret isn't configured, with no "unconfigured means open" fallback.

**Error handling assumptions:** 401 on auth failure, 413 if the event batch exceeds 100 events; individual blob-download or non-PDF-blob failures are silently skipped with no per-event failure signal back to Event Grid (the schema has none) — the whole batch always reports success once past auth/size checks.

**Known divergences:** None new this session.

**Gaps (carried forward, not re-verified this session):** Per `TOPOLOGY.md`'s Engineer Review item 5, the actual Azure Event Grid subscription's configuration status (secret generated and set as a delivery header) was not re-confirmed this session — the code-side fix (auth, container-pinning, request cap) is confirmed complete, but whether this integration point is actually live in production is unknown from source alone.

---

## IP-011 — Microsoft Fabric Warehouse

**Called by:** M-037 itself (`get_fabric_connection()`); transitively, M-003, M-017, M-045, M-046 (every caller of `execute_sql_fabric()`/`execute_query_fabric()`)

**What the application promises to send:** Parameterized SQL, written to be valid on both SQLite (the local/test fallback) and T-SQL (the real Fabric path) — no `LIMIT`/`TOP`, no `INSERT OR REPLACE` (see IC-15's PARTIAL enforcement note).

**What the application assumes it will receive:** Rows as list-of-dict results, structurally identical in shape to `execute_query()`'s output — but with **no dialect translation and no connection-drop retry**, unlike the Azure SQL path.

**Auth mechanism:** Azure CLI-issued token (`AzureCliCredential` + `SQL_COPT_SS_ACCESS_TOKEN`), reusing an existing `az login` session — not the ODBC driver's own interactive auth flow (confirmed abandoned after failing with FA004/0x534 on the development machine).

**Error handling assumptions:** None specific to this path — any connection or query failure propagates immediately, with no retry logic equivalent to Azure SQL's `_run_with_retry()`.

**Known divergences:** **New this session (see `TOPOLOGY.md`'s STAGE-2-DIVERGENCE and `INVARIANT_CATALOGUE.md` IC-15/IC-19):** the promise of full backend-agnosticism for callers (IC-15) does not fully hold for this integration point — callers must know which of the three cut-over tables is on Fabric, and the `id`-assignment concurrency gap (IC-19) is a genuine, currently-unenforced constraint on this integration point specifically.

**Gaps:**
1. **No automated schema-creation or sync mechanism exists for the Fabric side at all** — unlike Azure SQL (which has `src/lakehouse/azure_sql_migrations.py`, M-039, mirroring the SQLite migrations), nothing in this codebase creates or tracks the Fabric Warehouse's table structure. `scripts/test_fabric_connection.py` (M-045) only *queries* `INFORMATION_SCHEMA.TABLES` to confirm what's already there — there is no equivalent of M-039 for Fabric. This is a genuine, unaddressed gap, worth its own RISK_REGISTER entry.
2. The `id`-assignment concurrency gap (IC-19) — every write to a Fabric-cut-over table computes `MAX(id) + 1` in application code, unenforced by any lock or the database itself.
3. Requires an interactively-established `az login` session on whatever machine/process runs this code — not obviously compatible with a fully automated, headless production deployment (e.g. a container that starts fresh with no prior interactive Azure CLI session) without a separate, undocumented provisioning step to establish that session non-interactively.

---

Session E Part 1 (INTEGRATION_CONTRACTS.md) is complete. Part 2 (RISK_REGISTER.md) follows.
