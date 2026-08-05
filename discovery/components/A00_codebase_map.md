## A00 — Codebase Map
Produced by: BCE Stage 2 Session A0 (CC) — fresh Path A extraction, superseding the archived 2026-07-23 map
Date: 2026-08-05

Excluded from traversal: `.git/`, `discovery/` (BCE's own artifacts — self-referential, not application code; includes `discovery/_archive_2026-07/`, the prior extraction, kept for reference), `venv/` (not present in this checkout), `.pytest_cache/` (generated), `sample_data/` (test-fixture PDFs, enumerated once below rather than file-by-file), `node_modules/` (not applicable — no JS toolchain). `lakehouse/` (SQLite DB + `ai_call_slots/` lock files) and `backup/` (gitignored DB snapshot) are referenced in the archived map but do not exist in this checkout — both are runtime-generated/gitignored, not committed.

**Baseline note:** the archived A00 map (2026-07-23) predates PBVI/BCE-sprint adoption entirely (no `docs/ARCHITECTURE.md`, `docs/INVARIANTS.md`, `enhancements/` existed yet) and predates the 2026-07-25 scoped refresh (4 modules: batches router, intake_trigger webhook, concurrency limiter, shop-owner routing — none appear in that map despite being in the codebase since 2026-07-24/25). This map reflects the full current tree; unchanged-file descriptions are carried forward from the archived map only where independently consistent with the current listing, not assumed.

### [root]
- `.deployment` — Azure App Service deployment config (`SCM_DO_BUILD_DURING_DEPLOYMENT=true`).
- `.dockerignore` — excludes secrets (`.env`), VCS, and the Windows venv from the Docker build context.
- `.env.example` — template of every environment variable the pipeline and web app read.
- `.gitignore` — standard Python ignores plus `lakehouse/*.db`, `logs/*.log`, `venv/`, `backup/`.
- `Claude.md` — root-level one-line stub (`See docs/Claude.md`) — tool-compatibility shim only, not authoritative content (per `PROJECT_MANIFEST.md`).
- `DOCKER.md` — Docker packaging documentation; packaging-only, no pipeline logic changes.
- `Dockerfile` — Python 3.12-slim image; installs `tesseract-ocr` + `poppler-utils` alongside `requirements.txt`.
- `PIPELINE_VERIFICATION_REPORT.md` — **new since archived map.** Live pipeline test report (added `7bd6c9f`, 2026-08-05): 7 findings from direct testing (migration drift, OCR fallback zero-yield, untested Level 2/tolerance paths, worker poll-interval latency, corrupted-PDF raw-traceback crash, `gold_reconciliation_summary` staleness, a stale RULES.md claim), plus test-artifact/DB-row cleanup notes. Several findings already fixed in commits since (see Known Pain Points in `INTAKE_SUMMARY.md`) — this report itself is a point-in-time record, not automatically current.
- `PROJECT_MANIFEST.md` — **new since archived map.** PBVI file registry + sprint index; independently confirmed stale against `enhancements/REGISTRY.md` (see `INTAKE_SUMMARY.md` Known Pain Points).
- `README.md` — project overview.
- `RULES.md` — numbered deliberate-decision rules with enforcement-point references; not re-read in full this pass (only head/tail) — confirm rule count and latest entries in Session A/D.
- `check_queue.py` — ad hoc dev script: deletes stale rows from `validation_document_review_queue` for one named test PDF.
- `check_subprocess.py` — ad hoc dev script: debugging probe for the SQLite/Azure-SQL backend switch (`_using_azure_sql()`).
- `docker-compose.yml` — single `app` service; mounts `lakehouse/`/`sample_data/` as volumes.
- `requirements.txt` — pinned dependencies (Claude/OpenAI/Gemini/Mistral SDKs, `pyodbc`, `azure-storage-blob`, `fastapi`).
- `startup.sh` — Azure App Service startup command (`uvicorn web.app:app`).
- `test_worker_sim.py` — ad hoc dev script: runs the full pipeline via subprocess outside the actual worker.
- `test_worker_sim2.py` — ad hoc dev script: mimics `web/worker.py`'s exact path construction.

### config/ai/
- `active_provider.json` — runtime-read provider chain config; `provider_chain[0] = "claude_sonnet"` is ground truth for what `client_factory.get_ai_client()` resolves.
- `azure_claude_sonnet.json` — Claude Sonnet 4.6 config variant; archived map flagged this as possibly orphaned (not in `provider_config_paths`) — re-added/present again per `7bd6c9f`'s diff; confirm registration status in Session A.
- `azure_doc_intel.json`, `azure_gpt5_1.json`, `azure_gpt5_mini.json`, `azure_gpt5_nano.json`, `claude.json`, `claude_sonnet_extraction.json`, `gemini.json`, `mistral.json` — per-provider config files, one per registered (mostly dormant) AI client.

### config/document_types/
- `registry.json` — declares recognized document types (`VENDOR_STATEMENT` active).

### config/matching/
- `matching_rules.json` — match hierarchy config (Level 1 invoice+amount-tolerance, Level 2 RO+amount) and tolerance thresholds. **Confirmed 2 levels, matching `src/matching/engine.py`'s `MATCH_LEVEL_TO_TYPE` exactly** — no drift between this config and the code.

### config/mock_erp/
- `scenario_config.json` — controls Mock ERP's planted exceptions; modified per `PIPELINE_VERIFICATION_REPORT.md`'s own note (pre-existing, unrelated to that session) plus `7bd6c9f`'s diff — confirm current contents in Session A, not assumed unchanged from archived description.

### config/schema/
- `universal_financial_document_schema.json` — the schema every AI provider's output must conform to.

### config/validation/
- `extraction_rules.json` — structural validation rules, `confidence_threshold: 0.60`.

### config/ (top-level file)
- `shop_owners.json` — `vendor_id → shop owner` routing table, read by `src/shop_owners.py` and looked up whenever a new `gold_exceptions` row is written (`migrations/009_add_routing_aging.sql`'s `shop_owner` column).

### docs/
- `ARCHITECTURE.md` — **new since archived map** (PBVI adoption). v2.0, 2026-07-27. Read in full this pass.
- `Claude.md` — **new since archived map.** v2.0, FROZEN 2026-07-27. Read in full this pass.
- `INVARIANTS.md` — **new since archived map.** v1.2, 2026-07-27; sign-off status DRAFT (reverted, no review record found). Read in full this pass.
- `VIVE_Implementation_Context.md` — living implementation tracker predating PBVI adoption; **not re-read this pass** — flagged open in `INTAKE_SUMMARY.md`.
- `VIVE_Architecture_Updated.docx`, `VIVE_Improvement_Plan_Simple_Updated.docx`, `VIVE_Scope_Updated.docx` — **new since archived map**, added in `7bd6c9f` (2026-08-05), replacing three PDFs the archived `INTAKE_SUMMARY.md` cited by name (`VIVE_Scope_Final_Architecture (1).pdf`, `VIVE_Improvement_Plan_Simple (1).pdf`, `VIVE_Architecture_After_Planned_Changes (1).pdf` — all three now deleted). **Content of the three new `.docx` files is unreviewed by anyone as of this map** — flagged as an open item, see Session A0 Notes below.

### enhancements/
- `REGISTRY.md` — **new since archived map.** ENH-001 (COMPLETE), ENH-007 (CANCELLED), SPRINT-001 (CLOSED 2026-07-28).
- `SPRINT-001/ENH-001-automated-batch-intake/ENH-001_BCE_IMPACT.md`, `ENH-001_BRIEF.md` — ENH-001's enhancement package; not read in full this pass.
- `SPRINT-001/SPRINT-001_LOG.md` — sprint event log; not read in full this pass.
- `SPRINT-001/SPRINT-001_MANIFEST.md` — read in full this pass; confirms collision surface analysis (Prompt 2) never ran for SPRINT-001.
- `backlog/ENH-007-match-confidence-score/ENH-007_BRIEF.md` — cancelled enhancement's original brief stub; not read in full this pass.

### migrations/
- `001_initial_schema.sql` — original schema (Bronze/Silver/Gold, audit/intake logs, review queue, cache).
- `002_exception_dispositions.sql` — `exception_dispositions` table.
- `003_add_blob_storage_path.sql` — Blob Storage linkage columns on `document_intake_log`.
- `004_add_users_table.sql` — `users` table (bcrypt password_hash).
- `005_add_jobs_table.sql` — `jobs` table (background job queue).
- `006_add_job_claim_token.sql` — `claim_token` column for atomic job claiming.
- `007_add_batch_id_to_jobs.sql` — **new since archived map.** `batch_id` column on `jobs`, supporting the Event Grid auto-intake batch grouping.
- `008_add_match_confidence.sql` — **new since archived map.** `match_confidence` column on `gold_matched_invoices`/`gold_exceptions`.
- `009_add_routing_aging.sql` — **new since archived map.** Adds `shop_owner`, `escalation_status`, `escalated_at`, `escalated_by` to `gold_exceptions`. **Does not add `days_open`** — the migration's own header comment explains this is deliberate: SQLite's `GENERATED ALWAYS AS` columns can't reference the current time, so unlike Azure SQL (which does compute `days_open` as a true generated column, see `src/lakehouse/azure_sql_migrations.py`), the app computes "days open" in Python instead (`web/queries.py`'s `_days_since()`) on both backends.

### notebooks/
- `00_setup_lakehouse_schema.py` — applies all pending migrations via the migration runner.
- `01_document_intake.py` — main intake pipeline: cache check → AI extraction → validation → Bronze → Silver → intake log. Modified in `7bd6c9f` and `7e2d811` (corrupted-PDF `CorruptedPDFError` handling) since the archived map's read — re-verify docstring/chain-naming currency in Session A rather than trusting the archived note.
- `02_generate_mock_erp.py` — CLI entry point for the Mock ERP generator; the generator itself gained a `renumbered_invoices` controlled-exception type in `d77f305` — confirm this notebook's CLI surface reflects it.
- `03_run_matching.py` — CLI entry point for the deterministic matching engine.
- `04_generate_report.py` — CLI report generator with optional `--explain`; reads `gold_reconciliation_summary` directly — the exact read path `3cc3c37` fixed at the source (`score_overall_status()`/`_recompute_summary_counts()`).

### scripts/
- `run_full_pipeline.py` — single-command full pipeline runner; the same script `web/worker.py` invokes as a subprocess.
- `test_fabric_connection.py` — **new since archived map**, added `7bd6c9f` (2026-08-05). Smoke test connecting via `src/lakehouse/connection.py`'s new `get_fabric_connection()` and querying `INFORMATION_SCHEMA.TABLES` — first evidence of the Fabric Lakehouse cut-over in progress.
- `test_provider_chain.py` — smoke test: prints the resolved provider chain and confirms each client loads.

### src/ai/
- `audit_logger.py` — writes every AI call to `ai_audit_log`.
- `azure_openai_client.py` — `AzureOpenAIClient`, dormant (not in active chain).
- `base_client.py` — `AIClient` abstract interface + `AIResponse` dataclass.
- `claude_client.py` — Claude Haiku 4.5 client via Azure Foundry; used by `ExplanationService`.
- `claude_sonnet_client.py` — Claude Sonnet 4.6 client via Azure Foundry (streaming), active primary extraction path. Archived map noted this file's own docstring wrongly disclaimed itself as inactive — per the archived `ANNOTATION_CHECKLIST.md`, this was corrected in the 2026-07-24 documentation sweep; confirm still correct in Session A.
- `client_factory.py` — the only file that reads `active_provider.json` and instantiates concrete clients.
- `concurrency_limiter.py` — **new since archived map** (2026-07-24/25 scoped refresh). Cross-process, disk-based semaphore (`lakehouse/ai_call_slots/`) limiting concurrent Claude Sonnet calls to `VIVE_MAX_CONCURRENT_AI_CALLS` — needed because each job runs in its own subprocess, so an in-process `threading.Semaphore` can't coordinate across workers. Known accepted limitation: a killed process's lock file is never cleaned up (RISK_REGISTER R-010 in archived set).
- `document_intelligence_client.py` — Azure Document Intelligence client, dormant.
- `document_understanding_engine.py` — core AI stage: resolves provider via `client_factory`, falls back to pdfplumber on primary failure.
- `explanation_service.py` — narrative explanations for exceptions via Claude Haiku, decoupled from the extraction chain.
- `gemini_client.py` — Gemini 2.5 Flash client, dormant.
- `mistral_client.py` — Mistral Medium client, dormant (per-page rasterization required).
- `ocr_extractor.py` — pytesseract-based OCR text extraction for scanned pages.
- `pdfplumber_fallback.py` — last-resort deterministic extraction. Modified in `6aadbf1` (2026-08-05): `_ocr_text_to_pseudo_table()`'s column-split logic now falls back to any-whitespace-run splitting when the 2+-space split collapses a line to one cell — fixes a real 0-invoice-extracted bug on OCR'd scans with single-space column gaps.

### src/lakehouse/
- `azure_sql_migrations.py` — one-shot, re-runnable T-SQL schema creator for Azure SQL.
- `connection.py` — storage-backend abstraction point. **Materially changed since the archived map**: still selects Azure SQL (pyodbc) vs. SQLite based on `AZURE_SQL_SERVER`, but `7bd6c9f` (2026-08-05) added `get_fabric_connection()` (Azure CLI token auth against a Fabric SQL endpoint, falling back to local SQLite when Azure SQL isn't configured) plus `execute_sql_fabric()`/`execute_query_fabric()` helpers — scoped, per its own docstring, to `extraction_cache` only so far. This is the first landed code for the planned Fabric Lakehouse migration.
- `migrations.py` — numbered SQLite migration runner with `schema_version` bookkeeping.

### src/matching/
- `engine.py` — deterministic matching engine, **2 levels confirmed** (`MATCH_LEVEL_TO_TYPE = {1: "INVOICE", 2: "RO"}`) — a third "fuzzy prefix" level was deliberately removed (RULE-11) after it silently cross-matched unrelated invoices. Zero AI. Also contains `score_overall_status()`, extracted in `3cc3c37` so `run_matching()` and `web/queries.py`'s `_recompute_summary_counts()` share identical RECONCILED/MINOR_EXCEPTIONS/EXCEPTIONS_PRESENT tiering.

### src/mock_erp/
- `generator.py` — Mock ERP generator from Silver vendor-statement rows with deterministic planted exceptions. Gained a `renumbered_invoices` exception type in `d77f305` (2026-08-05) — the only exception type able to make Level 1 fail while Level 2 (RO+amount) still succeeds, closing a real gap (0 of 1,940 historical `gold_matched_invoices` rows were ever Level 2 before this).

### src/
- `normalization.py` — `normalize_invoice_number()`; no suffix/prefix stripping by design (RULE-01).
- `shop_owners.py` — **new since archived map** (2026-07-24/25 scoped refresh). `vendor_id → shop owner` routing lookup for `gold_exceptions.shop_owner` (config in `config/shop_owners.json`), called from every `gold_exceptions` write site so a new exception always gets a routing owner.

### src/storage/
- `blob_client.py` — `BlobStorageClient` for Azure Blob PDF archival; never raises (returns `None` on failure). Confirmed wired into the pipeline (`notebooks/01_document_intake.py` Step 8) per the archived `TOPOLOGY.md`'s Stage-2 correction — the older Implementation Context's "not yet wired" claim is stale.

### src/pipeline/, src/validation/
- Still empty (`__init__.py` only, no modules) as of this pass — same open question as the archived map: dead scaffolding or an unbuilt placeholder. Confirm intent in Session A.

### tests/
- `test_ai_clients.py`, `test_azure_openai_client.py`, `test_blob_client.py`, `test_claude_sonnet_client.py`, `test_document_intelligence_client.py`, `test_document_understanding_engine.py`, `test_explanation_service.py`, `test_gemini_client.py`, `test_lakehouse_connection.py`, `test_matching_engine.py`, `test_web_queries.py` — present in the archived map, offline/unit-level tests per provider or component.
- `test_batches.py` — **new since archived map.** Tests for the batches router/UI (`web/routers/batches.py`).
- `test_concurrency_limiter.py` — **new since archived map.** Tests for `src/ai/concurrency_limiter.py`.
- `test_exceptions_bulk_approve.py` — **new since archived map.** Tests for bulk-approve on `web/routers/exceptions.py`.
- `test_exceptions_escalate.py` — **new since archived map.** Tests for exception escalation routing/aging.
- `test_intake_trigger.py` — **new since archived map.** Tests for the Event Grid webhook (`web/routers/intake_trigger.py`), presumably including the R-009 auth-fix coverage.
- `test_level2_matching_integration.py` — **new since archived map**, added `d77f305` (2026-08-05). End-to-end integration test proving Level 2/tolerance matching fires through the real `run_intake()` → mock ERP → matching pipeline, not just via direct `classify_match()` unit calls (PIPELINE_VERIFICATION_REPORT.md Finding 4).
- `test_pdfplumber_fallback.py` — **new since archived map.** Tests for the OCR fallback path, likely including regression coverage for the `6aadbf1` column-split fix.
- `test_shop_owners.py` — **new since archived map.** Tests for `src/shop_owners.py`.
- `test_worker.py` — **new since archived map.** Tests for `web/worker.py`'s pool/claim behavior.

### web/
- `app.py` — FastAPI entry point; starts the background worker pool on lifespan startup, mounts all routers, session middleware for login.
- `deps.py` — shared FastAPI dependencies (Jinja2 templates/filters, `require_login`, sidebar counts). Contains `friendly_dt()`, confirmed (archived `RISK_REGISTER.md` R-011) to hardcode IST for all displayed timestamps — real gap, not yet fixed.
- `queries.py` — all SQL access for the web app. Gained `_recompute_summary_counts()` in `3cc3c37`, called from `resolve_exception()`.
- `start.py` — launches `uvicorn web.app:app --reload --port 8000`.
- `worker.py` — background thread pool (default 3, `VIVE_WORKER_POOL_SIZE`); polls `jobs` every 30s, claims atomically per-`pdf_filename` via `claim_next_pending_job()`, runs `scripts/run_full_pipeline.py` as a subprocess.

### web/routers/
- `auth.py` — session-based login/logout; bcrypt-verified against `users`, with a documented hardcoded fallback credential (archived `RISK_REGISTER.md` R-007).
- `batches.py` — **new since archived map** (2026-07-24/25). `/batches` and `/batches/{batch_id}` — lists batches newest-first (Event Grid deliveries share a `batch_id`; manual uploads are `batch_id = NULL`, grouped by date instead).
- `dashboard.py` — home page: KPIs from Gold tables (live-queries `gold_exceptions` per Claude.md Rule 3), recent runs, active jobs.
- `exceptions.py` — exceptions-by-vendor list and review/resolution flow; writes `exception_dispositions`, marks `gold_exceptions` RESOLVED, triggers the `3cc3c37` summary-recompute path.
- `intake_trigger.py` — **new since archived map** (2026-07-24/25). Azure Event Grid webhook (`/api/intake-trigger`) for auto-intake from the `viverecondropzone`/`incoming-statements` drop zone; code-complete with shared-secret auth (R-009 fix) but not yet deployed (blocked on Azure RBAC permissions).
- `jobs.py` — `/jobs` (JSON status, polled by dashboard) and `/jobs/history`.
- `reports.py` — reconciliation run list and per-statement report detail.
- `review_queue.py` — review flow for `validation_document_review_queue` rows.
- `upload.py` — accepts PDF upload(s), saves to `sample_data/`, enqueues a `jobs` row per file — never runs the pipeline synchronously.
- `users.py` — user list/add/remove, flat permission model (no RBAC).

### web/static/
- `app.js` — upload-page file-list UI + "Queuing..." overlay.
- `style.css` — shared stylesheet, sourced from `web_mockups/*.html`.

### web/templates/
- `base.html` — shared layout all other templates extend.
- `login.html`, `home.html`, `upload.html`, `users.html`, `reports.html`, `report_detail.html`, `jobs_history.html` — one page each per the router of the same name.
- `batch_detail.html`, `batches.html` — **new since archived map.** Batches router's two views.
- `exceptions_vendors.html`, `exceptions_review.html` — exceptions router's two views.
- `review_queue_vendors.html`, `review_queue_review.html` — review-queue router's two views.

### web_mockups/
- `vive_01_login.html` through `vive_05_upload.html` — static HTML design mockups; design references, not served by the app.

### sample_data/ (not enumerated file-by-file — test fixtures)
- Vendor-statement PDFs used for testing/extraction. Archived map noted a likely duplicate (`KSI Noakers 053126.pdf` / `KSI_Noakers_053126.pdf`, identical size); `PIPELINE_VERIFICATION_REPORT.md` (2026-08-05) independently confirms additional untracked test PDFs were added and left in place during verification testing (`KSI_Noakers_053126_RENAMED_copy.pdf`, `KSI_Noakers_053126_ONEBYTE_test.pdf`, three `Synthetic_ConcurrencyTest_*.pdf`, `Corrupted_NotAPDF_test.pdf`) — not committed to git, your call on cleanup per that report.

---

## Session A0 Notes — Flagged for Engineer Review Before Session A

**1. Three replacement `.docx` files in `docs/` are completely unreviewed.** `VIVE_Architecture_Updated.docx`, `VIVE_Improvement_Plan_Simple_Updated.docx`, `VIVE_Scope_Updated.docx` were added in the same commit that deleted the three PDFs the *previous* `INTAKE_SUMMARY.md` cited by name. Nobody — including this session — has opened them. Their content relative to the deleted originals is unknown. This is the single largest open unknown carried into this fresh pass.

**2. The Fabric Lakehouse migration has real code on the ground, scoped narrowly.** `src/lakehouse/connection.py`'s `get_fabric_connection()`/`execute_sql_fabric()`/`execute_query_fabric()` plus `scripts/test_fabric_connection.py` (all `7bd6c9f`, today) are the first landed pieces of a larger planned migration (13 tables per the engineer's stated priority list). Today's scope is `extraction_cache` only, per the code's own docstring — confirm in Session A whether anything already calls the Fabric path in a live code path, or whether it's genuinely isolated to the smoke test.

**3. Four real behavior fixes since the archived BCE pass are not yet reflected in any discovery/ artifact** (this map is the first to catch up): `gold_reconciliation_summary` staleness (`3cc3c37`), OCR fallback 0-yield bug (`6aadbf1`), corrupted-PDF raw-traceback crash (`7e2d811`), and Level 2/tolerance matching's previously-untested-in-production status (`d77f305`, via a new Mock ERP exception type). All four should be confirmed directly against the actual current code in Session A rather than taken from this map or from `PIPELINE_VERIFICATION_REPORT.md` alone.

**4. `R-011` (`friendly_dt()` hardcodes IST) remains unfixed** — confirmed still present in `web/deps.py` as of this pass. Carried forward as a genuine open risk, not resolved by any of the six commits since the last BCE pass.

**5. `config/ai/azure_claude_sonnet.json`'s registration status needs re-confirming** — the archived map flagged it as possibly orphaned (not in `active_provider.json`'s `provider_config_paths`); it reappears in `7bd6c9f`'s diff, worth checking whether that changed anything about its registration.

**6. `docs/VIVE_Implementation_Context.md` was not re-read this pass** — it predates PBVI adoption and may itself now be stale relative to `docs/ARCHITECTURE.md`/`docs/INVARIANTS.md`; needs a currency check in Session A/D rather than being assumed still authoritative for anything `ARCHITECTURE.md` doesn't already supersede.

**7. Untracked test artifacts from `PIPELINE_VERIFICATION_REPORT.md`'s live testing session remain in `sample_data/`** — six new PDF files, none committed to git. Not a code issue, but should be dispositioned (kept or removed) before this map's `sample_data/` description is treated as final.

An engineer must review this codebase map against `INTAKE_SUMMARY.md` before Session A begins.
