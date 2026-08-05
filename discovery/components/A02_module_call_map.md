## Module Roster — VIVE Reconciliation
Generated: 2026-08-05 by BCE Stage 2 Session A (CC)
Note: these IDs are permanent. Do not reassign at later sessions.

Fresh Path A extraction — full source read of every file in `discovery/components/A00_codebase_map.md`, superseding the archived roster's numbering entirely (not an incremental refresh). 50 modules, M-001–M-050.

| ID | Module Name | Source File | Layer |
|---|---|---|---|
| M-001 | FastAPI entry point | `web/app.py` | serving |
| M-002 | Shared web dependencies (templates, auth, filters) | `web/deps.py` | serving |
| M-003 | Web query layer | `web/queries.py` | serving |
| M-004 | Uvicorn launcher | `web/start.py` | serving |
| M-005 | Background worker pool | `web/worker.py` | serving |
| M-006 | Auth router | `web/routers/auth.py` | serving |
| M-007 | Dashboard router | `web/routers/dashboard.py` | serving |
| M-008 | Exceptions router | `web/routers/exceptions.py` | serving |
| M-009 | Jobs router | `web/routers/jobs.py` | serving |
| M-010 | Reports router | `web/routers/reports.py` | serving |
| M-011 | Review queue router | `web/routers/review_queue.py` | serving |
| M-012 | Upload router | `web/routers/upload.py` | serving |
| M-013 | Users router | `web/routers/users.py` | serving |
| M-014 | Batches router | `web/routers/batches.py` | serving |
| M-015 | Intake trigger router (Event Grid webhook) | `web/routers/intake_trigger.py` | serving |
| M-016 | Lakehouse schema setup entry point | `notebooks/00_setup_lakehouse_schema.py` | pipeline |
| M-017 | Document intake pipeline | `notebooks/01_document_intake.py` | pipeline |
| M-018 | Mock ERP generation entry point | `notebooks/02_generate_mock_erp.py` | pipeline |
| M-019 | Matching engine entry point | `notebooks/03_run_matching.py` | pipeline |
| M-020 | Report generation entry point | `notebooks/04_generate_report.py` | pipeline |
| M-021 | Full pipeline orchestrator | `scripts/run_full_pipeline.py` | pipeline |
| M-022 | AI client contract (`AIClient`/`AIResponse`) | `src/ai/base_client.py` | pipeline |
| M-023 | AI client factory | `src/ai/client_factory.py` | pipeline |
| M-024 | Document understanding engine | `src/ai/document_understanding_engine.py` | pipeline |
| M-025 | Claude Sonnet 4.6 client (active primary) | `src/ai/claude_sonnet_client.py` | pipeline |
| M-026 | Claude Haiku 4.5 client | `src/ai/claude_client.py` | pipeline |
| M-027 | Azure OpenAI client (dormant) | `src/ai/azure_openai_client.py` | pipeline |
| M-028 | Azure Document Intelligence client (dormant) | `src/ai/document_intelligence_client.py` | pipeline |
| M-029 | Gemini client (dormant) | `src/ai/gemini_client.py` | pipeline |
| M-030 | Mistral client (dormant) | `src/ai/mistral_client.py` | pipeline |
| M-031 | pdfplumber fallback extraction | `src/ai/pdfplumber_fallback.py` | pipeline |
| M-032 | OCR extractor (Tesseract) | `src/ai/ocr_extractor.py` | pipeline |
| M-033 | Exception explanation service | `src/ai/explanation_service.py` | pipeline |
| M-034 | Matching engine | `src/matching/engine.py` | pipeline |
| M-035 | Mock ERP generator | `src/mock_erp/generator.py` | pipeline |
| M-036 | Invoice number normalization | `src/normalization.py` | pipeline |
| M-037 | Lakehouse connection (storage backend abstraction) | `src/lakehouse/connection.py` | infra |
| M-038 | SQLite migration runner | `src/lakehouse/migrations.py` | infra |
| M-039 | Azure SQL schema creator | `src/lakehouse/azure_sql_migrations.py` | infra |
| M-040 | AI audit logger | `src/ai/audit_logger.py` | infra |
| M-041 | AI-call concurrency limiter | `src/ai/concurrency_limiter.py` | infra |
| M-042 | Shop owner routing lookup | `src/shop_owners.py` | infra |
| M-043 | Blob Storage client | `src/storage/blob_client.py` | infra |
| M-044 | Provider chain smoke test | `scripts/test_provider_chain.py` | infra |
| M-045 | Fabric Warehouse connection smoke test | `scripts/test_fabric_connection.py` | infra |
| M-046 | Review queue cleanup script | `check_queue.py` | infra |
| M-047 | Azure SQL detection probe | `check_subprocess.py` | infra |
| M-048 | Worker simulation (basic) | `test_worker_sim.py` | infra |
| M-049 | Worker simulation (exact path replication) | `test_worker_sim2.py` | infra |
| M-050 | Level 2 matching real-pipeline integration test | `tests/test_level2_matching_integration.py` | infra |

**Module-worthiness notes (BCE-009):** M-044–M-050 are test/harness files registered as modules because each makes a real, traceable call into other registered modules as its primary mechanism (a real DB read/write, a real subprocess pipeline run, a real client instantiation) rather than merely asserting against already-modeled behavior via mocks. M-050 specifically runs the real `run_intake()` → `generate_mock_erp()` → `run_matching()` chain against a real temporary SQLite database — only the AI network call is faked.

**Not registered as modules (assessed, excluded):** the remaining 20 files under `tests/` were not individually re-read this session (see `discovery/INTAKE_SUMMARY.md`'s Documents Reviewed) — by naming convention and the archived roster's precedent, these are unit-level tests against mocked/offline fixtures for a single already-modeled component, not independent dispatch mechanisms. This is a carried-forward assessment, not a fresh verification — flagged as a Session A follow-up if any of these turn out to run real cross-module chains the way M-050 does.

**Empty packages (confirmed, not modules):** `src/pipeline/__init__.py` and `src/validation/__init__.py` contain no code — verified this session (`ls` shows `__init__.py` only in each, 0 bytes of logic). Same open question as the archived map: dead scaffolding or an unbuilt placeholder — Session A cannot resolve intent from source alone.

---

## Section 1 — Internal Call Table

| Edge | Call Site (file:line) | Sync/Async |
|---|---|---|
| M-001 --[CALLS]--> M-005 | `web/app.py:33,35` (`lifespan()` — `start_worker()`/`stop_workers()`) | S |
| M-001 --[CALLS]--> M-006 through M-015 | `web/app.py:54-63` (`app.include_router(...)`, all 10 routers) | S |
| M-002 --[CALLS]--> M-003 | `web/deps.py:33-36` (`sidebar_context()` → `get_open_exceptions_count()`/`get_pending_review_count()`) | S |
| M-005 --[CALLS]--> M-003 | `web/worker.py:56,82,91,93,103,114,118` (`queries.claim_next_pending_job()`, `update_job_status()`, `get_vendor_name_for_statement()`) | S |
| M-005 --[CALLS]--> M-021 | `web/worker.py:67-75` (`subprocess.run([...scripts/run_full_pipeline.py...])`) | **A** (process boundary — see Async Boundaries #1) |
| M-006 --[CALLS]--> M-003 | `web/routers/auth.py:29` (`queries.get_user_by_email()`) | S |
| M-007 --[CALLS]--> M-003 | `web/routers/dashboard.py:22-25` (`get_kpis()`, `get_recent_runs()`, `get_active_jobs()`, `get_recent_completed_batches()`) | S |
| M-008 --[CALLS]--> M-003 | `web/routers/exceptions.py:39,42,62,71,85-90,113,134,146,158` (vendor summaries, aging, open exceptions, bulk-approve, escalate, resolve) | S |
| M-009 --[CALLS]--> M-003 | `web/routers/jobs.py:29,36` (`get_active_jobs()`, `get_job_history()`) | S |
| M-010 --[CALLS]--> M-003 | `web/routers/reports.py:22,30` (`get_all_runs()`, `get_statement_report()`) | S |
| M-011 --[CALLS]--> M-003 | `web/routers/review_queue.py:35,55,79` (review queue vendors/detail/action) | S |
| M-012 --[CALLS]--> M-003 | `web/routers/upload.py:72` (`queries.create_job()`) | S |
| M-013 --[CALLS]--> M-003 | `web/routers/users.py:22,42,47,59` (list/get/create/delete user) | S |
| M-014 --[CALLS]--> M-003 | `web/routers/batches.py:24,25,33` (`get_all_batches()`, `get_manual_uploads()`, `get_batch_detail()`) | S |
| M-015 --[CALLS]--> M-003 | `web/routers/intake_trigger.py:109` (`queries.create_job()`) | S |
| M-015 --[CALLS]--> M-043 | `web/routers/intake_trigger.py:102-106` (`BlobStorageClient(...).download_pdf()`) | S |
| M-021 --[CALLS]--> M-017 | `scripts/run_full_pipeline.py:75,77` (dynamic `load_notebook()` + `intake_mod.run_intake()`) | S (in-process, via `importlib`) |
| M-021 --[CALLS]--> M-035 | `scripts/run_full_pipeline.py:104-106` (`generate_mock_erp()`, `normalize_erp_to_silver()`) | S |
| M-021 --[CALLS]--> M-034 | `scripts/run_full_pipeline.py:116-117` (`run_matching()`) | S |
| M-021 --[CALLS]--> M-020 | `scripts/run_full_pipeline.py:125-126` (dynamic `load_notebook()` + `report_mod.generate_report()`) | S |
| M-017 --[CALLS]--> M-024 | `notebooks/01_document_intake.py:56-57,695-696` (`extract_pdf_text()`, `DocumentUnderstandingEngine().understand()`) | S |
| M-017 --[CALLS]--> M-036 | `notebooks/01_document_intake.py:373` (`normalize_invoice_number()`) | S |
| M-017 --[CALLS]--> M-042 | `notebooks/01_document_intake.py:283,338` (`get_shop_owner()`) | S |
| M-017 --[CALLS]--> M-043 | `notebooks/01_document_intake.py:570` (`BlobStorageClient().upload_pdf()`) | S |
| M-017 --[CALLS]--> M-034 | `notebooks/01_document_intake.py:59,282` (`score_exception_confidence()`) | S |
| M-017 --[CALLS]--> M-037 | `notebooks/01_document_intake.py:58` + throughout (`execute_sql`/`execute_query`/`execute_sql_fabric`/`execute_query_fabric`) | S |
| M-024 --[CALLS]--> M-023 | `src/ai/document_understanding_engine.py:200` (`client_factory.get_ai_client()`) | S |
| M-024 --[CALLS]--> M-031 | `src/ai/document_understanding_engine.py:43,238` (`extract_with_pdfplumber()` — fallback path) | S |
| M-024 --[CALLS]--> M-040 | `src/ai/document_understanding_engine.py:44,207-218` (`log_ai_call()`) | S |
| M-023 --[CALLS]--> M-025/M-026/M-027/M-028/M-029/M-030 | `src/ai/client_factory.py:38-98` (lazy per-branch `import` + instantiate — exactly one selected at runtime by `provider_chain[0]`) | S |
| M-025 --[CALLS]--> M-041 | `src/ai/claude_sonnet_client.py:49,212,331` (`ai_call_slot()` context manager around the real network call) | S |
| M-025 --[CALLS]--> M-031 | `src/ai/claude_sonnet_client.py:401` (`extract_with_pdfplumber()` — truncation row-count cross-check only) | S |
| M-028 --[CALLS]--> M-031 | `src/ai/document_intelligence_client.py:39-44` (`_extract_header_info`/`_extract_invoice_row`/`_find_header_row`/`_map_columns` — shared column-mapping helpers) | S |
| M-029 --[CALLS]--> M-031 | `src/ai/gemini_client.py:435` (`extract_with_pdfplumber()` — truncation row-count cross-check only) | S |
| M-031 --[CALLS]--> M-032 | `src/ai/pdfplumber_fallback.py:49,314` (`is_ocr_available()`, `ocr_page()`) | S |
| M-035 --[CALLS]--> M-036 | `src/mock_erp/generator.py:240,268` (`normalize_invoice_number()`) | S |
| M-035 --[CALLS]--> M-037 | `src/mock_erp/generator.py:24` + throughout (`execute_sql`/`execute_query`) | S |
| M-034 --[CALLS]--> M-037 | `src/matching/engine.py:29` + throughout (`execute_sql`/`execute_query`) | S |
| M-034 --[CALLS]--> M-042 | `src/matching/engine.py:30,338` (`get_shop_owner()`) | S |
| M-020 --[CALLS]--> M-033 | `notebooks/04_generate_report.py:42,118` (`ExplanationService().explain_all_open_exceptions()`) | S |
| M-020 --[CALLS]--> M-037 | `notebooks/04_generate_report.py:41` + throughout (`execute_query`/`execute_query_fabric`) | S |
| M-033 --[CALLS]--> M-023 | `src/ai/explanation_service.py:26,148` (`client_factory.get_ai_client("claude")`) | S |
| M-033 --[CALLS]--> M-040 | `src/ai/explanation_service.py:27,162` (`log_ai_call()`) | S |
| M-033 --[CALLS]--> M-037 | `src/ai/explanation_service.py:28` + throughout (`execute_sql`/`execute_query`) | S |
| M-040 --[CALLS]--> M-037 | `src/ai/audit_logger.py:14,37` (`execute_sql()`) | S |
| M-003 --[CALLS]--> M-037 | `web/queries.py:20` + throughout (`execute_query`/`execute_sql`/`execute_query_fabric`/`execute_sql_fabric`) | S |
| M-003 --[CALLS]--> M-034 | `web/queries.py:21,137,1192-1193` (`score_exception_confidence()`, `score_overall_status()`) | S |
| M-003 --[CALLS]--> M-042 | `web/queries.py:22,1216` (`get_shop_owner()`) | S |
| M-016 --[CALLS]--> M-037 | `notebooks/00_setup_lakehouse_schema.py:21,26,46` (`get_connection()`) | S |
| M-016 --[CALLS]--> M-038 | `notebooks/00_setup_lakehouse_schema.py:22,28` (`apply_pending_migrations()`) | S |
| M-039 --[CALLS]--> M-037 | `src/lakehouse/azure_sql_migrations.py:32,381,438` (`get_connection()`) | S |
| M-044 --[CALLS]--> M-023 | `scripts/test_provider_chain.py:6,16` (`get_ai_client()`, `get_provider_chain()`) | S |
| M-045 --[CALLS]--> M-037 | `scripts/test_fabric_connection.py:11,14` (`get_fabric_connection()`) | S |
| M-046 --[CALLS]--> M-037 | `check_queue.py:5,11,15` (`execute_sql_fabric()`, `execute_query_fabric()`) | S |
| M-047 --[CALLS]--> M-037 | `check_subprocess.py:4-8` (imports `_using_azure_sql` inside a spawned subprocess) | **A** (process boundary) |
| M-048 --[CALLS]--> M-021 | `test_worker_sim.py:8-16` (`subprocess.run([...run_full_pipeline.py...])`) | **A** (process boundary) |
| M-049 --[CALLS]--> M-021 | `test_worker_sim2.py:13-21` (`subprocess.run([...run_full_pipeline.py...])`, reproducing `web/worker.py`'s exact path construction) | **A** (process boundary) |
| M-050 --[CALLS]--> M-017 | `tests/test_level2_matching_integration.py:146-158` (dynamic-load `run_intake()`) | S |
| M-050 --[CALLS]--> M-035 | `tests/test_level2_matching_integration.py:161-164` (`generate_mock_erp()`, `normalize_erp_to_silver()`) | S |
| M-050 --[CALLS]--> M-034 | `tests/test_level2_matching_integration.py:179-180` (`run_matching()`) | S |
| M-050 --[CALLS]--> M-038 | `tests/test_level2_matching_integration.py:31,109` (`apply_pending_migrations()`) | S |

External-system call sites (see A03 in `discovery/TOPOLOGY.md` for the full IP-NNN records):

| Edge | Call Site | Sync/Async |
|---|---|---|
| M-025 --[CALLS]--> IP-001 (Claude Sonnet 4.6) | `src/ai/claude_sonnet_client.py:214-221,333-356` (`client.messages.stream()`) | S (streaming, in-process wait) |
| M-026 --[CALLS]--> IP-002 (Claude Haiku 4.5) | `src/ai/claude_client.py:116-123,430-451` (`client.messages.create()`) | S |
| M-027 --[CALLS]--> IP-003 (Azure OpenAI) | `src/ai/azure_openai_client.py:172,666` (`client.responses.create()`) | S |
| M-028 --[CALLS]--> IP-004 (Azure Document Intelligence) | `src/ai/document_intelligence_client.py:173-176` (`client.begin_analyze_document()`) | S |
| M-029 --[CALLS]--> IP-005 (Gemini) | `src/ai/gemini_client.py:227-231,297-306` (`client.models.generate_content()`) | S |
| M-030 --[CALLS]--> IP-006 (Mistral) | `src/ai/mistral_client.py:186-193,312-324` (`client.chat.completions.create()`) | S |
| M-032 --[CALLS]--> IP-007 (Tesseract/Poppler) | `src/ai/ocr_extractor.py:67-74,97-103` (`pytesseract.image_to_string()`, `convert_from_path()`, local binaries) | S |
| M-037 --[CALLS]--> IP-008 (Azure SQL/SQLite) | `src/lakehouse/connection.py:126-150` (`pyodbc.connect()`/`sqlite3.connect()`) | S |
| M-043 --[CALLS]--> IP-009 (Azure Blob Storage) | `src/storage/blob_client.py:127-136,190-196` (`BlobServiceClient`) | S |
| IP-010 (Azure Event Grid) --[CALLS]--> M-015 | `web/routers/intake_trigger.py:118-138` (inbound `POST /api/intake-trigger`) | **A** (external, inbound HTTP) |
| M-037 --[CALLS]--> IP-011 (Fabric Warehouse) | `src/lakehouse/connection.py:75-119` (`get_fabric_connection()`, `pyodbc.connect()` via `AzureCliCredential`) | S |

---

## Section 2 — Startup Sequence

| Step | Module (M-NNN) | Action | Failure Mode (STARTUP-FATAL / NON-FATAL) |
|---|---|---|---|
| 1 | M-001 | `load_dotenv(PROJECT_ROOT/.env)` — explicit path (Rule 4) | NON-FATAL — missing `.env` silently leaves env vars unset; downstream connection code then falls back to SQLite/dormant-provider defaults rather than crashing here |
| 2 | M-001 | Import all 10 router modules (M-006–M-015) | **STARTUP-FATAL** — a Python import error in any router (e.g. a syntax error, a missing dependency) prevents the ASGI app object from being constructed at all |
| 3 | M-001 | `FastAPI(lifespan=lifespan)` constructed, `SessionMiddleware` added with `WEB_SESSION_SECRET` (falls back to a hardcoded dev default if unset) | NON-FATAL — app starts regardless; an unset secret is a silent security downgrade, not a crash (see archived `RISK_REGISTER.md` R-008) |
| 4 | M-001 | Static files mounted at `/static` | **STARTUP-FATAL** if the static directory path is invalid; otherwise NON-FATAL |
| 5 | M-001 → M-005 | `lifespan()` startup phase calls `start_worker()` | NON-FATAL — `start_worker()` itself has no failure path that halts app startup; if `threading.Thread.start()` somehow failed the exception would propagate and abort startup (STARTUP-FATAL), but no such case is observed in source |
| 6 | M-005 | Worker pool threads (`VIVE_WORKER_POOL_SIZE`, default 3) begin polling `jobs` every 30s (`POLL_INTERVAL_SECONDS`) | NON-FATAL — each worker's loop catches all exceptions internally (`traceback.print_exc()`) and continues |
| 7 | — | App ready to serve requests | — |

Router registration order (step 2) also matters for two POST routes on `web/routers/exceptions.py` — `/exceptions/{vendor_name}/bulk-approve` and `/exceptions/{vendor_name}/escalate` must be declared before the generic `/exceptions/{vendor_name:path}` POST handler, or Starlette's greedy path converter would swallow both suffixes into `vendor_name` and those two routes would never be reached (confirmed directly in `web/routers/exceptions.py:120-149` — the file itself declares them in this order with an explicit comment explaining why).

## Section 3 — Async Boundaries

| Producer (M-NNN) | Consumer (M-NNN) | Mechanism | Failure behaviour |
|---|---|---|---|
| M-012 (upload router) | M-005 (worker pool) | `jobs` table row (status=PENDING), polled every 30s | None at the producer — fire-and-forget; a stuck/never-claimed job simply sits PENDING (no dead-letter or alert) |
| M-015 (intake_trigger router) | M-005 (worker pool) | `jobs` table row (status=PENDING, tagged `batch_id`, `submitted_by="event-grid"`), polled every 30s | Same as above — no per-event failure signal back to Event Grid beyond the initial 401/413 |
| IP-010 (Azure Event Grid, external) | M-015 (intake_trigger router) | Inbound `POST /api/intake-trigger`, shared-secret header auth | Fails closed: 401 if `VIVE_EVENTGRID_WEBHOOK_SECRET` unset or header mismatch; 413 if event batch exceeds `MAX_EVENTS_PER_REQUEST` (100) |
| M-005 (worker pool) | M-021 (`scripts/run_full_pipeline.py`) | `subprocess.run([...], timeout=1800)` — one OS process per job | Non-zero exit code or missing `"Statement ID:"` marker in captured stdout/stderr → job marked FAILED, last 4000 chars of output stored as `error_message`. 30-minute hard timeout kills the subprocess. |
| M-047 (`check_subprocess.py`) | (ad hoc probe) | `subprocess.run([sys.executable, "-c", ...])` — one-off diagnostic subprocess | Captured stdout/stderr printed directly; no retry, no timeout guard in this dev script |
| M-048/M-049 (worker simulation scripts) | M-021 (`scripts/run_full_pipeline.py`) | `subprocess.run([...], timeout=60/600)` | Same shape as the real worker's boundary — these scripts exist specifically to reproduce it outside the actual worker thread |

**Note on M-021's own internal calls (Section 1):** `run_full_pipeline.py`'s calls into `notebooks/01_document_intake.py` and `notebooks/04_generate_report.py` use `importlib.util.spec_from_file_location()` to load them as modules (they are numbered CLI scripts, not package members) — this is a same-process, synchronous in-process call, not a subprocess boundary, despite the dynamic-loading mechanism looking unusual at a glance.
