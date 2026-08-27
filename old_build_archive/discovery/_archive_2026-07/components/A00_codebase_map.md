## A00 — Codebase Map
Produced by: BCE Stage 2 Session A0 (CC)
Date: 2026-07-23

Excluded from traversal: `venv/` (vendored Python environment, analogous to node_modules), `.git/`, `.pytest_cache/` (generated), `backup/` (gitignored DB snapshot — one file present, `reconciliation_20260713_163325.db`, a pre-Gemini→Claude-switch backup per Implementation Context Progress Log 2026-07-13).

### [root]
- `.deployment` — Azure App Service deployment config (`SCM_DO_BUILD_DURING_DEPLOYMENT=true`), confirms this deploys to Azure App Service (Phase 3 "Shared hosting").
- `.dockerignore` — excludes secrets (`.env`), VCS, and the Windows venv from the Docker build context.
- `.env` — live secrets/config (not read in detail — contains credentials; present, git-ignored).
- `.env.example` — template of every environment variable the pipeline and web app read, with inline comments on which client/config consumes each; includes vars for Azure OpenAI, Azure Document Intelligence, Claude (Haiku, via Azure Foundry), and (per file naming pattern) is the reference for what should also cover Claude Sonnet/Gemini/Mistral/Azure SQL/Blob vars.
- `.gitignore` — standard Python ignores plus `lakehouse/*.db`, `logs/*.log`, `venv/`, `backup/`.
- `DOCKER.md` — explains the Docker packaging is packaging-only, no pipeline logic changes; documents image contents and volume mounts.
- `Dockerfile` — Python 3.12-slim image; installs `tesseract-ocr` + `poppler-utils` (OCR/PDF rasterization system deps) alongside `requirements.txt`.
- `README.md` — project overview: AI-driven vendor statement reconciliation, no per-vendor config required.
- `RULES.md` — 13 numbered deliberate-decision rules with enforcement-point references (see INTAKE_SUMMARY.md for full digest).
- `check_queue.py` — ad hoc dev script: deletes stale rows from `validation_document_review_queue` for one named test PDF. Not part of the pipeline; a one-off cleanup utility.
- `check_subprocess.py` — ad hoc dev script: spawns a subprocess to print whether `_using_azure_sql()` resolves true/false and whether `AZURE_SQL_SERVER` is set — a debugging probe for the SQLite/Azure-SQL backend switch.
- `docker-compose.yml` — single `app` service; mounts `lakehouse/` and `sample_data/` as volumes, reads `.env` at container start (not baked into image).
- `docker-compose.yml` — (see above)
- `requirements.txt` — pinned/floor-versioned dependencies; notably includes `anthropic`, `openai`, `google-genai`, `pyodbc`, `azure-storage-blob`, `fastapi` — i.e. dependencies for Claude, Azure OpenAI, Gemini, Azure SQL, Blob Storage, and the FastAPI web app all simultaneously.
- `startup.sh` — Azure App Service startup command: `uvicorn web.app:app` from `/home/site/wwwroot` — confirms production entry point is the FastAPI app, not Streamlit.
- `test_worker_sim.py` — ad hoc dev script: runs the full pipeline via subprocess against a specific sample PDF outside the actual worker, to sanity-check subprocess invocation.
- `test_worker_sim2.py` — ad hoc dev script: same as above but explicitly mimics `web/worker.py`'s exact `pdf_path`/`relative_pdf_path` construction, to reproduce a worker-specific path bug.

### BCE/
- `SKILL.md`, `bce_core.md` — byte-identical BCE Core methodology skill, v2.6 (governing this session).
- `bce_signal.md` — BCE-S (non-code source extraction) methodology skill, v1.0.
- `History/*.md`, `*.docx` — versioned methodology history (v1.1 through v3.1, plus original DG-OS docx) — not part of the VIVE application, tooling/process artifacts only.

### config/ai/
- `active_provider.json` — **the actual runtime-read provider chain config**: `provider_chain: ["claude_sonnet", "pdfplumber"]`. Its own `_comment` field states Claude Sonnet 4.6 (`claude_sonnet_client.py`) is "the permanent primary extraction engine," superseding both `azure_doc_intel` and Gemini. This is the ground-truth default `get_ai_client()` resolves to — see Notes below on how many other files disagree with it.
- `azure_claude_sonnet.json` — Claude Sonnet 4.6 config variant (20000 max output tokens, 300s timeout) — appears unregistered in `active_provider.json`'s `provider_config_paths` (only `claude_sonnet_extraction.json` is registered under key `claude_sonnet`); possible orphaned/superseded config, to confirm in Session A.
- `azure_doc_intel.json` — Azure Document Intelligence config (`model_id: prebuilt-layout`).
- `azure_gpt5_1.json`, `azure_gpt5_mini.json`, `azure_gpt5_nano.json` — three Azure OpenAI Responses-API deployment configs, same `AzureOpenAIClient` class.
- `claude.json` — Claude Haiku 4.5 config (original/explanation-service provider).
- `claude_sonnet_extraction.json` — Claude Sonnet 4.6 config registered under `provider_config_paths.claude_sonnet` (64000 max output tokens, 600s timeout) — the one `active_provider.json` actually resolves.
- `gemini.json` — Gemini 2.5 Flash config.
- `mistral.json` — Mistral Medium config (image-only, no native PDF support per client docstring).

### config/document_types/
- `registry.json` — declares which document types the system recognizes (`VENDOR_STATEMENT` active for reconciliation; others parked in Bronze only).

### config/matching/
- `matching_rules.json` — deterministic match hierarchy (Level 1 exact invoice+amount, Level 2 RO+amount) and tolerance thresholds (`amount_tolerance_pct: 0.01`, `amount_tolerance_abs: 0.50`).

### config/mock_erp/
- `scenario_config.json` — controls the deterministic Mock ERP generator's planted exceptions (missing/mismatch/duplicate).

### config/schema/
- `universal_financial_document_schema.json` — the single contract every AI provider's output must conform to before entering the pipeline.

### config/validation/
- `extraction_rules.json` — provider-agnostic structural validation: required fields, numeric/date fields, `confidence_threshold: 0.60`.

### discovery/
- `INTAKE_SUMMARY.md` — this session's Stage-1-equivalent intake artifact (Path A).
- `components/A00_codebase_map.md` — this file.

### docs/
- `VIVE_Implementation_Context.md` — living implementation tracker (system purpose, architecture, phased plan, dated Progress Log through 2026-07-15).
- `VIVE_Scope_Final_Architecture (1).pdf` — formal scope document; names Claude (Haiku 4.5) as the AI decision (stale — see Notes).
- `VIVE_Improvement_Plan_Simple (1).pdf` — plain-language priority table mirroring the phased plan; also names Claude (stale).
- `VIVE_Architecture_After_Planned_Changes (1).pdf` — pipeline diagram, Unchanged-vs-New per stage; also names Claude (stale).

### lakehouse/
- `reconciliation.db` — the live SQLite lakehouse database (Bronze/Silver/Gold + jobs/users/dispositions tables), local-dev/test backend.

### migrations/
- `001_initial_schema.sql` — original 10-table schema (Bronze/Silver/Gold, audit/intake logs, review queue, cache).
- `002_exception_dispositions.sql` — `exception_dispositions` table (disposition/audit trail), keyed on vendor+invoice+reason_code.
- `003_add_blob_storage_path.sql` — adds Blob Storage linkage columns to `document_intake_log`.
- `004_add_users_table.sql` — **`users` table (per-user logins, bcrypt password_hash)** — Phase 3 item the Implementation Context status table still marks "Not Started."
- `005_add_jobs_table.sql` — **`jobs` table (background job queue, PENDING/PROCESSING/COMPLETED/FAILED)** — Phase 3 item the Implementation Context status table still marks "Not Started."
- `006_add_job_claim_token.sql` — adds `claim_token` to `jobs` for atomic job claiming.

### notebooks/
- `00_setup_lakehouse_schema.py` — applies all pending migrations via the migration runner (no direct DDL).
- `01_document_intake.py` — main intake pipeline: cache check → AI extraction → validation → Bronze → Silver → intake log. Docstring names the extraction chain as "Azure Claude Sonnet 4.6 → pdfplumber/OCR" — the one file whose docstring roughly matches the actual `active_provider.json` chain.
- `02_generate_mock_erp.py` — CLI entry point for the Mock ERP generator (RULE-05 CLI-only boundary).
- `03_run_matching.py` — CLI entry point for the deterministic matching engine, produces Gold tables.
- `04_generate_report.py` — CLI report generator with optional `--explain`; docstring says explanations use "the active AI provider (Azure OpenAI gpt-5-mini)" — stale, per RULES.md the explain step hardcodes Claude directly via `explanation_service.py`, independent of the extraction chain.

### sample_data/
- Eight vendor-statement PDFs used for testing/extraction, including `KSI Noakers 053126.pdf` and `KSI_Noakers_053126.pdf` — identical file size (84,672 bytes), likely the same file present twice under two filenames (probably one saved by the web upload router, which preserves the original filename verbatim including spaces — see `web/routers/upload.py`). Worth confirming as a true duplicate, not two different statements, during Session A.

### scripts/
- `run_full_pipeline.py` — single-command full pipeline runner (intake → mock ERP → matching → report); the same script `web/worker.py` invokes as a subprocess for queued jobs.
- `test_provider_chain.py` — smoke test: prints the resolved provider chain from config and confirms each provider's client loads.

### src/ai/
- `audit_logger.py` — writes every AI call to `ai_audit_log`.
- `azure_openai_client.py` — `AzureOpenAIClient`, one class serving all three gpt-5 deployment configs; no longer in the active chain per `active_provider.json`, kept registered.
- `base_client.py` — `AIClient` abstract interface + `AIResponse` dataclass; the contract every provider adapter implements.
- `claude_client.py` — Claude Haiku 4.5 client via Azure Foundry; used by `ExplanationService`, not necessarily the extraction chain.
- `claude_sonnet_client.py` — Claude Sonnet 4.6 client via Azure Foundry (streaming); its own docstring calls itself "NOT part of the active provider chain (gemini remains primary)" — **contradicted by `active_provider.json`, which names `claude_sonnet` as `provider_chain[0]`**. See Notes.
- `client_factory.py` — the only file that reads `active_provider.json` and instantiates concrete clients; its inline per-provider comments (e.g. "Gemini — Active primary", "claude_sonnet — NOT part of the active chain") **contradict the config file it itself reads**. See Notes.
- `document_intelligence_client.py` — Azure Document Intelligence (`prebuilt-layout`) client; reuses pdfplumber's column-header interpreter.
- `document_understanding_engine.py` — core AI stage: resolves provider via `client_factory`, falls back to pdfplumber on primary failure. Docstring names the chain as "Azure OpenAI gpt-5-mini + pdfplumber/OCR" — stale.
- `explanation_service.py` — generates narrative explanations for exceptions via Claude directly, decoupled from the extraction provider chain; never alters match_status or financial figures.
- `gemini_client.py` — Gemini 2.5 Flash client; docstring calls itself "the active primary provider in active_provider.json" — **not true of the current config** (see Notes).
- `mistral_client.py` — Mistral Medium client (per-page rasterization required; PDF data URIs rejected by Mistral's API); registered, not in active chain.
- `ocr_extractor.py` — pytesseract-based OCR text extraction for scanned pages; docstring still names "Azure OpenAI gpt-5-mini" as primary — stale.
- `pdfplumber_fallback.py` — last-resort deterministic extraction (geometry-based + per-page OCR for scanned pages); OCR-derived rows get lower confidence (0.50 vs 0.65) per RULE-10.

### src/lakehouse/
- `azure_sql_migrations.py` — one-shot, re-runnable T-SQL schema creator for Azure SQL (parallel to the SQLite migration files, not a numbered migration runner itself).
- `connection.py` — single storage-backend abstraction point; selects Azure SQL (pyodbc) vs SQLite based on `AZURE_SQL_SERVER` env var; absorbs dialect differences (RULE-06, RULE-13).
- `migrations.py` — numbered SQLite migration runner with `schema_version` bookkeeping (RULE-12).

### src/matching/
- `engine.py` — deterministic 2-level matching engine (`classify_match()`, `run_matching()`); zero AI (RULE-03).

### src/mock_erp/
- `generator.py` — generates Mock ERP data from Silver vendor-statement rows with deterministic planted exceptions (RULE-05, RULE-06).

### src/
- `normalization.py` — `normalize_invoice_number()`; no suffix/prefix stripping by design (RULE-01).

### src/storage/
- `blob_client.py` — `BlobStorageClient` for Azure Blob PDF archival, keyed on the same SHA-256 `document_hash`; never raises (returns `None` on any failure). Per Implementation Context, not yet wired into the pipeline — worth confirming in Session A whether `web/routers/upload.py` or `web/worker.py` call it (initial read of both shows neither does; PDFs are saved to local `sample_data/` only).

### src/pipeline/, src/validation/
- Empty `__init__.py` only in each — packages exist but currently have no modules; possible placeholder for future refactor, or dead scaffolding. Flag for Session A confirmation.

### tests/
- `test_ai_clients.py` — ClaudeClient tests, offline/fake transport.
- `test_azure_openai_client.py` — AzureOpenAIClient tests, offline.
- `test_blob_client.py` — BlobStorageClient tests, offline.
- `test_claude_sonnet_client.py` — ClaudeSonnetClient tests incl. column-mapping/currency-guard logic, offline.
- `test_document_intelligence_client.py` — DocumentIntelligenceClient tests, offline.
- `test_document_understanding_engine.py` — engine-level tests with fake providers.
- `test_explanation_service.py` — ExplanationService tests, fake transport.
- `test_gemini_client.py` — GeminiClient tests incl. column-mapping logic, offline.
- `test_lakehouse_connection.py` — Azure SQL connection-drop retry logic tests, offline (fake pyodbc objects).
- `test_matching_engine.py` — pure unit tests on `classify_match()`.
- `test_web_queries.py` — tests `web/queries.py` vendor-summary functions against a real in-memory SQLite DB built from `migrations/001_initial_schema.sql` — **not present in the "45 tests / 6 pytest files" count Implementation Context Section 2 states**, confirming that count is stale (there are 11 test files today, several web/newer-client files postdating that count).

### web/
- `app.py` — **FastAPI** entry point (not Streamlit); starts the background worker on lifespan startup, mounts routers for auth/dashboard/exceptions/review_queue/upload/reports/users/jobs, session middleware for login.
- `deps.py` — shared FastAPI dependencies: Jinja2 templates + custom filters (money, dates, initials), `require_login`, sidebar context (open exception/review counts).
- `queries.py` — all SQL access for the web app (807 lines), layered on `src.lakehouse.connection`.
- `start.py` — launches `uvicorn web.app:app --reload --port 8000` from the project root.
- `worker.py` — background daemon-thread worker: polls `jobs` table every 30s, claims one PENDING job atomically, runs `scripts/run_full_pipeline.py` as a subprocess, records COMPLETED/FAILED; never crashes the loop on a single job's failure.

### web/routers/
- `auth.py` — session-based login/logout; bcrypt-verified against the `users` table, with a **hardcoded fallback credential** (module-level constants, see this file directly — value intentionally not reproduced here) kept deliberately until DB-backed users are confirmed working end-to-end (per its own docstring) — flag as a RISK_REGISTER candidate (hardcoded credential in source).
- `dashboard.py` — home page: KPIs from Gold tables + recent runs + active jobs.
- `exceptions.py` — exceptions-by-vendor list and per-vendor review/resolution flow; writes to `exception_dispositions` and marks `gold_exceptions` RESOLVED.
- `jobs.py` — `/jobs` (JSON status, polled by the dashboard for auto-refresh) and `/jobs/history`.
- `reports.py` — reconciliation run list and per-statement report detail.
- `review_queue.py` — separate review flow for `validation_document_review_queue` rows (extraction-incomplete/duplicate rows that never reach `gold_exceptions` on their own); actioning can raise a `gold_exceptions` row.
- `upload.py` — accepts PDF upload(s), saves to `sample_data/` under the original filename, enqueues a `jobs` row per file; never runs the pipeline synchronously.
- `users.py` — user list/add/remove; no role-based access control (any logged-in user can manage users) — consistent with RULE-08's flat-permission design intent, though RULE-08 was written before this page existed.

### web/static/
- `app.js` — upload-page file-list UI + "Queuing..." overlay (returns as soon as queued, not after pipeline completion).
- `style.css` — shared design tokens/stylesheet, sourced from `web_mockups/*.html`.

### web/templates/
- `base.html` — shared layout (nav/sidebar) all other templates extend.
- `login.html`, `home.html`, `upload.html`, `users.html`, `reports.html`, `report_detail.html`, `jobs_history.html` — one page each per the router of the same name.
- `exceptions_vendors.html`, `exceptions_review.html` — exceptions router's two views.
- `review_queue_vendors.html`, `review_queue_review.html` — review-queue router's two views.

### web_mockups/
- `vive_01_login.html` through `vive_05_upload.html` — static HTML design mockups (login, home, exceptions-vendors, exceptions-review, upload) that `web/static/style.css` and the live templates were built from. Design references, not served by the app.

---

## Session A0 Notes — Flagged for Engineer Review Before Session A

**1. The AI provider chain is a live, unresolved multi-way contradiction across at least 8 files — not a simple doc-staleness issue.** The only ground truth is what `client_factory.get_ai_client()` actually resolves at runtime: `active_provider.json`'s `provider_chain[0]` = `"claude_sonnet"` → `ClaudeSonnetClient` (Claude Sonnet 4.6 via Azure Foundry), with `pdfplumber` as fallback. Every one of the following disagrees with that, each apparently written at a different point in the provider's history and never updated:
   - RULES.md RULE-04 and `docs/VIVE_Implementation_Context.md` Section 3 → claim Azure Document Intelligence (`prebuilt-layout`) is primary.
   - `src/ai/gemini_client.py` docstring and `src/ai/client_factory.py`'s own inline comments → claim Gemini is "the active primary provider."
   - `src/ai/claude_sonnet_client.py`'s own docstring → claims itself "NOT part of the active provider chain (gemini remains primary)" — wrong about its own status.
   - `src/ai/document_understanding_engine.py`, `src/ai/ocr_extractor.py`, `notebooks/04_generate_report.py` → all claim Azure OpenAI gpt-5-mini is primary.
   - Only `notebooks/01_document_intake.py`'s docstring ("Azure Claude Sonnet 4.6 → pdfplumber/OCR") is roughly consistent with the actual config.
   This is the highest-priority item for Session A/D to confirm against actual execution (not another comment) and record as STAGE-2-DIVERGENCE — per the standing rule for this extraction, none of these comments should be trusted over the `provider_chain` value client_factory.py actually reads.

**2. A full FastAPI web application already exists — `web/`, 8 routers, Jinja2 templates, a background worker, per-user logins (bcrypt + `users` table), and a job queue (`jobs` table) — none of which appear as "Not Started" in `docs/VIVE_Implementation_Context.md`'s Phase 2/3 status tables.** The Implementation Context states the reviewer dashboard will be Streamlit; the code is FastAPI + Jinja2 + a polling background thread, not Streamlit, and not merely "started" but seemingly feature-complete (login, upload, jobs, exceptions review, review queue, reports, user management all have working routes and templates). This is a significant docs-vs-code divergence beyond simple staleness — the actual architecture direction changed without the living tracker being updated. Recommend confirming with the engineer whether Implementation Context's status tables are simply unmaintained past 2026-07-15, or whether this web app was built on a separate track.

**3. Hardcoded fallback credential in `web/routers/auth.py`** — a fallback email/password/name are defined as module-level constants and checked in `_authenticate()` alongside the real `users` table lookup, acknowledged in its own docstring as temporary but still present. Value intentionally not recorded here — see the file directly for the literal constants and their line numbers. Flag as a RISK_REGISTER candidate regardless of intent.

**4. `src/pipeline/` and `src/validation/` are empty packages** (`__init__.py` only, no modules) — either dead scaffolding or a placeholder for work not yet started; confirm intent in Session A.

**5. `config/ai/azure_claude_sonnet.json` appears orphaned** — not referenced in `active_provider.json`'s `provider_config_paths` (only `claude_sonnet_extraction.json` is registered under the `claude_sonnet` key). Confirm whether it's dead config.

**6. Duplicate sample PDF** — `sample_data/KSI Noakers 053126.pdf` and `sample_data/KSI_Noakers_053126.pdf` are identical in size; likely the same statement saved under two filenames (upload preserves the original filename verbatim, including spaces). Not a code issue, but could double-count in any full-directory batch run.

**7. Test count in `docs/VIVE_Implementation_Context.md` Section 2 ("45 tests across 6 pytest files") is stale** — there are 11 test files today (`tests/test_web_queries.py`, `tests/test_claude_sonnet_client.py`, and others postdate that count).

An engineer must review this codebase map against INTAKE_SUMMARY.md before Session A begins.
