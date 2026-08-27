# INTEGRATION_CONTRACTS.md — VIVE Reconciliation
Produced by: BCE Stage 2 Session E (CD) — Path A (Custodian-Led)
Date: 2026-07-24

Synthesized entirely from `discovery/TOPOLOGY.md` (A03), `discovery/MODULE_CONTRACTS.md`, and their component files — no new source reads performed for this artifact, per Session E's CD role.

---

## IP-001 — Claude Sonnet 4.6 (Anthropic, via Azure AI Foundry) — **confirmed active primary extraction provider**

**Called by:** M-023, reached via M-020 → M-031 → M-023 (`client_factory.get_ai_client()` with no argument, resolving `active_provider.json`'s `provider_chain[0]`)

**What the application promises to send:** The whole PDF as one base64-encoded document content block, in a single **streaming** Anthropic Messages call (`client.messages.stream()` + `get_final_message()` — required because a non-streaming call risks a read timeout on a long whole-document extraction). Sends its own embedded `EXTRACTION_PROMPT` — **not** the `VISION_PROMPT` that `document_understanding_engine.py` passes in; that argument is silently ignored.

**What the application assumes it will receive:** JSON `{vendor_name, statement_date, columns_found, rows: [{col: val, ...}]}`. Field-to-schema mapping (`invoice_date`, `outstanding_amount`, `ro_number`, etc.) happens afterward in Python via `_map_columns()`/`_row_to_invoice()`. **No per-row confidence field is requested at all.**

**Auth mechanism:** API key (`AZURE_CLAUDE_API_KEY`) + Azure AI Foundry endpoint routing (`anthropic.AnthropicFoundry`), deployment resolved via `AZURE_CLAUDE_SONNET_DEPLOYMENT`.

**Error handling assumptions:** Never raises — every failure path converts to a clean `AIResponse(success=False)`, which `document_understanding_engine.py` catches and falls through to the deterministic pdfplumber fallback (M-028). Truncation is explicitly detected and treated as an immediate fallback signal, not retried (a systematically truncated response would likely truncate again).

**Known divergences:**
- **[RESOLVED — Stage 3, 2026-07-24, engineer sign-off (P1-S3-002), corrected across three passes]** Nine separate code/doc locations (RULES.md RULE-04; Implementation Context; `gemini_client.py`'s docstring; `client_factory.py`'s own inline comments; `ocr_extractor.py`; `document_understanding_engine.py`'s docstring; `04_generate_report.py`'s docstring; `mistral_client.py`'s docstring; and `claude_sonnet_client.py`'s own docstring) each named a *different* provider as primary — all stale relative to this being the code-confirmed, currently-resolved primary. All nine are now corrected; see `discovery/ANNOTATION_CHECKLIST.md` P1-S3-002 for the three-pass completion history.
- **[RESOLVED — 2026-07-24]** `line_confidence` was fabricated (`ROW_CONFIDENCE = 0.75` constant), never elicited from the model — fixed 2026-07-24: this client now elicits and parses a genuine per-row confidence value instead (see IC-15, `discovery/RISK_REGISTER.md` R-001).
- **[RESOLVED — 2026-07-24]** No totals-row exclusion existed in either the prompt or the code — fixed 2026-07-24: a new `_is_totals_row()` check now filters these rows before they're ingested as invoice lines (see `discovery/RISK_REGISTER.md` R-002).

**Gaps:** No document-level unreadable-page handling exists in this client's own prompt (unlike `VISION_PROMPT`'s explicit instruction for that case). `page_number` is hardcoded to `1` for every row — no per-page tracking exists for this whole-document-call architecture.

---

## IP-002 — Claude Haiku 4.5 (Anthropic, via Azure AI Foundry) — explanation service only

**Called by:** M-029 (`ExplanationService`), via M-022 (`ClaudeClient`)

**What the application promises to send:** A plain-text prompt (`EXPLANATION_PROMPT_TEMPLATE`, populated with one exception's details), via `generate()` (non-streaming), `max_output_tokens` deliberately capped at 1024 (below the client's own 65536 default — avoids tripping the SDK's own "streaming required" guard for long requests, since this is a few sentences of JSON, not a document extraction).

**What the application assumes it will receive:** JSON `{probable_cause, suggested_resolution, confidence_score, business_impact}`.

**Auth mechanism:** API key (`AZURE_CLAUDE_API_KEY` — same env var name as IP-001, different deployment via `AZURE_CLAUDE_DEPLOYMENT`) + Azure AI Foundry routing.

**Error handling assumptions:** Retry-with-backoff (`max_retries` default 2). A failure on one exception marks that row `failed` and continues to the next — never aborts the batch.

**Known divergences:** None — this is the one client whose documented role (decoupled explanation generation, hardcoded independent of `provider_chain`) exactly matches its actual code behavior. `ClaudeClient`'s own `generate_with_file()` capability (real, model-elicited confidence) is never exercised by this caller, which only uses plain `generate()`.

**Gaps:** None identified.

---

## IP-003 — Azure OpenAI (gpt-5-mini / gpt-5-nano / gpt-5.1, Responses API) — registered, **not in the active chain**

**Called by:** M-021 — reachable only via an explicit `get_ai_client("azure_gpt5_mini"|"azure_gpt5_nano"|"azure_gpt5_1")` call; no confirmed live caller makes one.

**What the application promises to send:** One Responses API call **per page** (PDF split via `pypdf`) — `input_file` (text-layer pages, inline base64) or `input_image` (scanned pages, rasterized locally at 300 DPI via `pdf2image`) content blocks, plus the real `VISION_PROMPT` — **this client is one of only two (with IP-002's sibling, M-022) that actually honors the passed prompt.**

**What the application assumes it will receive:** JSON matching the Universal Financial Document Schema per page, aggregated across all pages into one document result — including a **genuine, model-reported `line_confidence`** per row, not a fabricated constant.

**Auth mechanism:** API key (`AZURE_OPENAI_API_KEY`) + endpoint (`AZURE_OPENAI_ENDPOINT`) + one of three deployment-name env vars.

**Error handling assumptions:** `temperature` is never forwarded (these reasoning models reject it with a 400). A `status == "incomplete"` response is explicitly detected and converted to a clean failure rather than an apparently-successful empty result. Per-page retry-once; one bad page doesn't abort the document.

**Known divergences:** Several stale docs/comments (`document_understanding_engine.py`'s own docstring, `ocr_extractor.py`, `04_generate_report.py`'s docstring) name this as the *current* primary — not true as of this session; it is dormant.

**Gaps:** Not reachable via the default `get_ai_client()` resolution — would require an explicit code change to re-activate.

---

## IP-004 — Azure Document Intelligence (`prebuilt-layout`) — registered, **a prior active primary**

**Called by:** M-024 — reachable only via explicit `get_ai_client("azure_doc_intel")`; no confirmed live caller.

**What the application promises to send:** The whole PDF in one call to the `prebuilt-layout` model — no prompt at all (not an LLM; `generate()` is a stub that always fails cleanly — only `generate_with_file()` is meaningful for this service).

**What the application assumes it will receive:** Raw table geometry (rows/cells, no semantic field labels), mapped via `pdfplumber_fallback.py`'s column-header interpreter (imported directly, not duplicated).

**Auth mechanism:** API key (`AZURE_DOC_INTEL_KEY`) + endpoint (`AZURE_DOC_INTEL_ENDPOINT`).

**Error handling assumptions:** Retry policy from config; explicit warning if zero tables are returned rather than a silent empty success; a `HEADER_MAX_DATA_START` guard specifically prevents misreading a trailing totals/summary row as a table header (a real, previously-encountered bug, now fixed).

**Known divergences:** RULES.md RULE-04 and Implementation Context both still name this as the *current* primary — stale, per IC-4.

**Gaps:** `line_confidence` is hardcoded (`ROW_CONFIDENCE = 0.75`), same as IP-001/005/006 — but for a structurally different, more defensible reason: this is pure table-geometry extraction with no content understanding, so there is no model self-assessment to elicit in the first place (see IC-15's scoping note).

---

## IP-005 — Google Gemini 2.5 Flash — registered, **apparently a prior active primary per its own docstring**

**Called by:** M-025 — reachable only via explicit `get_ai_client("gemini")`; no confirmed live caller.

**What the application promises to send:** The whole PDF via Files API upload + one `generate_content` call, the client's own `EXTRACTION_PROMPT` (not `VISION_PROMPT`).

**What the application assumes it will receive:** JSON `{vendor_name, statement_date, columns_found, rows}`, mapped in Python via `_map_columns()` — no per-row confidence requested.

**Auth mechanism:** API key (`GEMINI_API_KEY`).

**Error handling assumptions:** A dedicated retry path for 503 UNAVAILABLE specifically (up to 2 retries, 60s wait) — any other error fails immediately, no retry. Two-signal truncation detection (empty `rows` with non-empty `columns_found`, or a salvaged row count suspiciously low relative to `pdfplumber`'s own count on the same document). Uploaded file always cleaned up, best-effort.

**Known divergences:**
- This client's own module docstring, **and** `client_factory.py`'s own inline comment directly above the branch that instantiates it, both claim it is "the active primary provider" — directly false as of this session; `claude_sonnet` is `provider_chain[0]`.
- `line_confidence` is fabricated (`ROW_CONFIDENCE = 0.75` constant), never elicited from the model — same gap as IP-001; see IC-15, RISK_REGISTER R-001.
- No totals-row exclusion in either the prompt or the code — same gap as IP-001; see RISK_REGISTER R-002.

**Gaps:** None beyond what's captured above.

---

## IP-006 — Mistral Medium — registered, **never confirmed active at any point**

**Called by:** M-026 — reachable only via explicit `get_ai_client("mistral")`; no confirmed live caller.

**What the application promises to send:** One chat-completions call **per page** (PDF rasterized to PNG first — Mistral's `image_url` content part rejects raw `application/pdf` data URIs outright, confirmed via diagnostic testing per the module docstring), the client's own `EXTRACTION_PROMPT`.

**What the application assumes it will receive:** JSON `{columns_found, rows: [{raw: {...}, mapped: {...}}]}` — **deliberately does not ask for confidence or document/vendor/statement metadata at all**, a considered choice after diagnostic testing found Mistral's self-reported confidence and row counts unreliable (100% "HIGH" confidence regardless of known transcription errors; the model's own row count disagreeing with its own output on 12 of 14 test pages).

**Auth mechanism:** API key (`MISTRAL_API_KEY`) + endpoint (`MISTRAL_ENDPOINT`).

**Error handling assumptions:** Per-page retry-once (matching IP-003's pattern); the whole document only fails if every page failed.

**Known divergences:**
- No stale "I am primary" claim anywhere — the one AI provider clean on that specific point.
- `line_confidence` is fabricated (`ROW_CONFIDENCE = 0.75` constant) — same gap as IP-001/IP-005, though for a demonstrated-unreliable-signal rationale distinct from their cases; the downstream effect (defeats the 0.60 threshold) is identical. See IC-15, RISK_REGISTER R-001.
- No totals-row exclusion — same gap as IP-001/IP-005; see RISK_REGISTER R-002.

**Gaps:** Stashes the raw per-column dict into the schema's `description` field as JSON — explicitly marked TEMPORARY in the code, purely so the full per-vendor column set is inspectable in Bronze/Silver after a real run.

---

## IP-007 — Tesseract OCR + Poppler (local binaries) — last-resort text extraction

**Called by:** M-027, invoked by M-028 (`pdfplumber_fallback`)

**What the application promises to send:** A rasterized PDF page image (default dpi=200) to the local Tesseract binary via `pytesseract`.

**What the application assumes it will receive:** Raw OCR text, converted to a pseudo-table for the same column-mapping logic real pdfplumber tables use.

**Auth mechanism:** None — local binary, no network call, no API key.

**Error handling assumptions:** `is_ocr_available()` gracefully degrades to "unavailable" on any missing dependency or unreachable binary; per-page OCR attempted only where pdfplumber itself found no usable text layer.

**Known divergences:** None.

**Gaps:** `_configure_tesseract_path()` hardcodes a Windows-specific fallback binary path with no equivalent for Linux/macOS — relevant since the confirmed production target (Azure App Service, per `startup.sh`) is Linux.

---

## IP-008 — Lakehouse database (SQLite local/dev/test, Azure SQL production)

**Called by:** Nearly every module — M-011, M-013 (indirectly), M-014, M-016, M-017, M-019, M-032, M-033, M-034, M-035, M-036, M-037, M-041, M-042.

**What the application promises to send:** Parameterized SQL via `execute_sql()`/`execute_query()`, auto-translated for the Azure SQL dialect where needed (`INSERT OR REPLACE` → `MERGE`, trailing `LIMIT n` → `SELECT TOP n`) — confirmed a narrow, two-pattern translator, not a general-purpose one.

**What the application assumes it will receive:** Rows as `list[dict]` (`execute_query`) or a live cursor (`execute_sql`).

**Auth mechanism:** Azure SQL — username/password (`AZURE_SQL_USERNAME`/`AZURE_SQL_PASSWORD`) via a TLS-encrypted `pyodbc` connection string (`Encrypt=yes`). SQLite — none (local file).

**Error handling assumptions:** Dropped-connection retry specifically for pyodbc SQLSTATE `08S01`/`08001` (Azure SQL serverless auto-pause), up to 3 retries with a 5s wait — any other error propagates immediately, unretried.

**Known divergences:** None regarding the connection/query mechanism itself — but per IC-12, the *schema-provisioning* path diverges: SQLite goes through the tracked, numbered migration runner (M-034); Azure SQL goes through a separate, manually-synced one-shot creator (M-035) outside that tracked system entirely. See RISK_REGISTER R-006.

**Gaps:** The two-pattern SQL translator only covers the exact SQLite-only constructs this codebase currently uses — a new one (e.g. a bound `LIMIT ?` placeholder) would fail untranslated against Azure SQL; already worked around once in `web/queries.py:get_recent_runs()`.

---

## IP-009 — Azure Blob Storage (`vendor-statements` container)

**Called by:** M-039, invoked by M-014 — **confirmed wired end-to-end this session**, correcting Implementation Context's stale "not wired into the pipeline yet" claim.

**What the application promises to send:** One blob upload per PDF, path `{vendor_slug}/{yyyy}/{mm}/{document_hash}.pdf` (reusing the same SHA-256 hash already computed for extraction caching), with `original_filename`/`vendor_name`/`uploaded_by` attached as metadata.

**What the application assumes it will receive:** The blob's URL on success.

**Auth mechanism:** Connection string (`AZURE_BLOB_CONNECTION_STRING`).

**Error handling assumptions:** **Never raises, by design** — any failure (missing config, missing file, network/auth error) returns `None`; the caller logs a warning and continues without ever blocking the pipeline.

**Known divergences:** Implementation Context's Progress Log (dated 2026-07-15) states this is "not wired into the pipeline yet" — confirmed false; the actual call happens inside `notebooks/01_document_intake.py`'s `run_intake()` Step 8.

**Gaps:** No reader of Blob Storage exists anywhere in the traced codebase — archival is write-only from the pipeline's perspective; nothing currently retrieves an archived PDF back for display or audit.

---

## IP-010 — Azure Event Grid (auto-intake webhook, `viverecondropzone` storage account / `incoming-statements` container) — added 2026-07-25, code-complete but not yet deployed

**Called by:** M-046 (inbound HTTP POST from Azure Event Grid, not called by our code)

**What the application promises to send:** This is an inbound trigger — Event Grid initiates, not our code. On a valid, authorized delivery, M-046 calls M-039 (`BlobStorageClient`, a different container/connection-string than IP-009) to pull the referenced PDF down, then queues it as a job identically to a manual upload, tagged `submitted_by="event-grid"` with a shared `batch_id` per delivery (see M-045).

**What the application assumes it will receive:** Either a one-time Event Grid `SubscriptionValidationEvent` or a batch of `Microsoft.Storage.BlobCreated` events.

**Auth mechanism:** As of 2026-07-25, code-complete but not yet deployed: a shared secret (`VIVE_EVENTGRID_WEBHOOK_SECRET`), checked via constant-time comparison against a static delivery header, before anything else in the handler runs. Until this session, there was no authentication at all — see `discovery/RISK_REGISTER.md` R-009 for the full history and the still-open deployment action item (secret not yet generated/configured on the actual Event Grid subscription — blocked on Azure permissions).

**Error handling assumptions:** The download side is hard-pinned to the configured dropzone container regardless of what container the inbound event's blob URL names (see M-039's rewritten contract) — previously the URL's own container segment was trusted, a second finding fixed alongside the auth gap. A hard cap of 100 events per delivery was also added (no cap existed before).

**Known divergences:** None recorded — this integration point was added in the same 2026-07-25 pass that documents it; no stale prior claims exist about it.

**Gaps:** None beyond what's captured above.

---

Session E Part 1 (INTEGRATION_CONTRACTS.md) complete.
