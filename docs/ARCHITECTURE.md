# ARCHITECTURE.md — VIVE Reconciliation
Updated: 2026-10-30

## Changelog
| Version | Date | Author | Change |
|---|---|---|---|
| v1.0 | 2026-07-24 | CD | Brownfield initial |
| v2.0 | 2026-07-27 | Ayush Kumar Sinha | Full update — parallel workers, batch intake, review queue, match confidence, routing/aging, bulk approve, all new routes and tables added |
| v2.1 | 2026-08-05 | Ayush Kumar Sinha | **Storage platform migration.** Bronze, Silver, and Gold move from Azure SQL Database to **Microsoft Fabric**: Bronze → Fabric **Lakehouse**, Silver + Gold → Fabric **Warehouse**. Operational/workflow tables (jobs, exceptions, dispositions, review queue, audit log) move to a dedicated **Recon layer on SQL database in Fabric**, kept off Lakehouse/Warehouse because this data is live, transactional, and must never be treated as rebuildable. SQLite remains the local/dev backend, unchanged. |
| v2.2 | 2026-08-05 | Ayush Kumar Sinha (verified via Claude Code, direct code trace) | **Extraction chain and test count corrected against live code.** Confirmed active chain is Claude Sonnet 4.6 → pdfplumber (not Azure Document Intelligence). Confirmed pytesseract OCR is actively wired into the pdfplumber fallback, gated by a text-density check, with `extract_text_with_ocr()` identified as dead code. Test suite is actually 281 passed / 18 failed / 299 total — all 18 failures are local-environment issues (Azure CLI auth blocked on this machine, plus the known Windows tempfile lock), not code defects. This replaces a stale 45/46 figure. |
| v2.3 | 2026-08-05 | Ayush Kumar Sinha | **INV-01 confidence threshold raised from 0.60 to 0.90** (see INVARIANTS.md INV-01 v1.4 for full basis — recorded as an engineer judgment call, not data-validated). Propagated to `config/validation/extraction_rules.json`, `notebooks/01_document_intake.py`, and this doc. **Real consequence surfaced by this change:** the pdfplumber-fallback path's row confidence values (0.65 native, 0.50 OCR) were deliberately left unchanged, so both now fall below the new 0.90 gate — meaning all pdfplumber-fallback rows, OCR-derived or not, now route to human review rather than only the OCR ones. This was a deliberate choice (don't silently compensate for one decision with another) — verified via full test suite: 281 passed / 18 failed, identical failing tests to the pre-change baseline, confirming no regression from the threshold change itself. |
| v2.4 | 2026-08-06 | Ayush Kumar Sinha (verified via Claude Code, direct code trace) | **Correction: this document previously claimed the Fabric migration was "not yet implemented in code" (§2.3, §7, §8, §9) — false.** Direct re-read of `src/lakehouse/connection.py` confirms three Recon-classified tables (`extraction_cache`, `document_intake_log`, `validation_document_review_queue`) are already cut over via `get_fabric_connection()`/`execute_sql_fabric()`/`execute_query_fabric()` (lines 75-119, 255-289) — real, env-var-configured (`FABRIC_SQL_ENDPOINT`, `FABRIC_WAREHOUSE_NAME`), not mock/test-only. Corrected: these three tables target **Fabric Warehouse**, not "SQL database in Fabric" as the target-state bullets in §2.3/§4 describe — that phrase now describes only the target end-state. The Fabric Warehouse/target mismatch is the confirmed root cause of the IDENTITY/concurrency gap tracked as `discovery/RISK_REGISTER.md` R-012 / `discovery/INVARIANT_CATALOGUE.md` IC-19. Remaining Recon-classified tables (`jobs`, `exception_dispositions`, `users`, `ai_audit_log`) and all of Bronze/Silver/Gold remain unmigrated, still on Azure SQL/SQLite. Triggered by a teammate doc-review flag, verified against live code before editing — same discipline as prior verification passes. |
| v2.5 | 2026-08-06 | Ayush Kumar Sinha (executed via Claude Code) | **Migration completed: the three cut-over tables now live on a real SQL database in Fabric item — R-012/IC-19 resolved for these three tables.** A genuine "SQL database in Fabric" item was created in the Fabric workspace (`FABRIC_SQLDB_ENDPOINT`/`FABRIC_SQLDB_NAME`); schema created with real `IDENTITY(1,1)` primary keys via `scripts/create_fabric_sqldb_schema.py` (deliberately not a `migrations/` file — see that script's docstring for why a T-SQL file placed there broke the SQLite test-suite migration runner on the first attempt, since caught and fixed); 184 existing rows (`extraction_cache`=10, `document_intake_log`=15, `validation_document_review_queue`=159) migrated via `scripts/migrate_fabric_data_to_sqldb.py` — no FK references into these tables anywhere in the codebase (confirmed by grep before migrating), fresh IDs assigned on insert. `get_fabric_connection()` repointed to the new target (same auth mechanism — `AzureCliCredential`, no interactive/WAM-broker auth — same signature, no caller changes, per Rule 6). Verified: row counts match exactly via both a direct check and the live `execute_query_fabric()` app path; full test suite (`pytest tests/`) at 298 passed / 1 failed / 299 total (1 pre-existing Windows tempfile issue, unrelated) — better than the documented 281/18 baseline, because this session's environment has working Azure CLI auth where the original baseline's did not. **The old Fabric Warehouse copies of these three tables were deliberately left in place** as a rollback safety net — decommissioning them is a separate, not-yet-approved step. Remaining Recon tables (`jobs`, `exception_dispositions`, `users`, `ai_audit_log`) and all of Bronze/Silver/Gold are still unmigrated. |
| v3.0 | 2026-10-30 | Vaishali Rao Yellur (via Claude Code) | **Dead content removed; body rewritten against current code.** Matching is against NetSuite (`src/matching/fabric_matching.py`, Fabric copy or SuiteAnalytics Connect), not a mock ERP; storage table reflects SQLite / Azure SQL / SQL database in Fabric / Lakehouse / Warehouse as used today; extraction adds the per-vendor Python route and the validation gate; removed providers dropped; route table regenerated from the app; intake lists the live drop zone and mailbox Logic Apps. Removed: the §9 migration prompt (its starting state no longer exists), blocked-deployment notes (App Service and Event Grid are live), resolved gaps, and pointers to deleted files (`INVARIANTS.md`, `RULES.md`, `discovery/`, removed scripts). |

---

## 1. What This System Is

VIVE Reconciliation is a Python-based AI-powered accounts payable automation tool built for VIVE Collision, a multi-shop auto body repair company (~79 shops, Northeast US). Vendor suppliers send monthly PDF statements; the system extracts line-item data from each PDF, compares it against VIVE's NetSuite vendor bills and credits, and surfaces discrepancies for the AP team to review — replacing a manual, hours-long per-vendor cross-check.

**It does not itself approve, reject, or execute payments** — it identifies discrepancies for a human to act on. The optional NetSuite write-back (`docs/NETSUITE_WRITEBACK.md`) only marks records reconciled or flags exceptions.

---

## 2. Shape of the System

A FastAPI web app queues each PDF as a job; a worker pool runs `scripts/run_full_pipeline.py` per job, which loads `notebooks/01_document_intake.py` (extraction, validation, Bronze), builds Silver, runs matching, optionally writes back to NetSuite, and loads `notebooks/04_generate_report.py`.

### 2.1 Layers

| Layer | What lives here |
|---|---|
| Serving | FastAPI + Jinja2 web app, server-rendered. Routers in `web/routers/`: auth, dashboard, exceptions, jobs, reports, review_queue, upload, users, batches, intake_trigger, mailbox_sync, validation, statements, netsuite_connect. |
| Pipeline | Extraction (per-vendor Python extractors, Claude Sonnet 4.6, pdfplumber/OCR fallback), validation gate, Silver build (dbt or direct), matching against NetSuite, NetSuite write-back, background worker pool (3 workers). |
| Infra | Data-access layer (`src/lakehouse/`), migration runners, AI client factory, audit logger, concurrency limiter, blob/SharePoint storage clients. |

### 2.2 Storage

| Store | Used for | Code |
|---|---|---|
| **SQLite** | Local/dev/test — everything below that isn't Fabric | `src/lakehouse/connection.py`, schema from `migrations/` |
| **Azure SQL** (`AZURE_SQL_SERVER`) | `jobs`, `exception_dispositions`, `users`, `ai_audit_log`, older `gold_*` tables | `get_connection()`/`execute_sql()`/`execute_query()` |
| **SQL database in Fabric** (`FABRIC_SQLDB_ENDPOINT`) | `extraction_cache`, `document_intake_log`, `validation_document_review_queue` (real `IDENTITY(1,1)` keys) | `get_fabric_connection()`/`execute_sql_fabric()`/`execute_query_fabric()` |
| **Fabric Lakehouse** | Bronze `bronze.raw_statement`; Silver `silver.statement_line`; nightly NetSuite copy `bronze.netsuite_vendorbill`/`vendorcredit`/`vendor` | `src/lakehouse/bronze_raw.py`, `dbt/vive_recon/`, `src/lakehouse/silver_build.py` |
| **Fabric Warehouse** | Matching results `silver.recon_matched_invoices`/`recon_exceptions`/`recon_summary` | `src/matching/fabric_matching.py`, schema `scripts/create_fabric_recon_schema.py` |

Bronze/Silver are rebuildable from source. The operational tables (jobs, dispositions, review queue, audit log) carry who-did-what history and must never be rebuilt. Lakehouse, Warehouse and SQL databases are different engines — nothing should assume one transaction spans two of them.

### 2.3 Extraction

`notebooks/01_document_intake.py`'s `_determine_extraction_route()` picks one of two routes per PDF:

- **Python library** — text-layer statements from vendors mapped in `src/extraction/python_library/adapter.py` (`_FIELD_MAP`), one hand-written extractor per vendor layout. Rows carry confidence 1.0.
- **AI** — scanned PDFs and every other vendor. Chain from `config/ai/active_provider.json`: `["claude_sonnet", "pdfplumber"]`.
  - **Claude Sonnet 4.6** (Azure AI Foundry, `config/ai/claude_sonnet_extraction.json`) reads the whole PDF as a native document. Call path: `src/ai/document_understanding_engine.py` → `src/ai/client_factory.py` → `src/ai/claude_sonnet_client.py`. Returns genuine per-row confidence.
  - **pdfplumber + Tesseract OCR** (`src/ai/pdfplumber_fallback.py`) if Claude fails. When a page's native text is under 500 chars (`OCR_TRIGGER_TEXT_THRESHOLD`), `ocr_page()` in `src/ai/ocr_extractor.py` OCRs it and the text goes through the same column mapping. Row confidence 0.65 native / 0.50 OCR — both under the 0.90 gate, so every fallback row routes to human review.
- Claude Haiku 4.5 (`config/ai/claude.json`, `src/ai/explanation_service.py`) writes exception explanations only — never extraction.

Chain history: Claude Haiku 4.5 → Azure OpenAI gpt-5-mini → Azure Document Intelligence → Claude Sonnet 4.6 (column-mapping quality on multi-invoice-column vendors). The earlier providers were deleted from the code on 2026-10-30.

**Validation gate** (`src/validation/gate.py`, on unless `VALIDATION_GATE_ENABLED=false`): a statement whose totals don't reconcile stops before matching and completes with a "Validation failed" note; rows under 0.90 confidence go to `validation_document_review_queue`.

### 2.4 Matching

`src/matching/fabric_matching.py` — 100% deterministic, no AI. It reads the statement's Silver lines and NetSuite bills/credits, and writes matched/exception rows to the Warehouse recon tables. Its module docstring is the reference for the rules (A–D: single charge → bill, single credit/payment → credit memo, charge + equal reversal → bill, otherwise earliest charge wins). Credits match by substring, bills by exact tranid. Per-vendor line-selection rules and NetSuite entity overrides live in `config/` and the dbt seeds.

NetSuite source (`NETSUITE_SOURCE`, `src/netsuite/connect_source.py`): `fabric` (default, nightly Lakehouse copy) or `connect` (live read-only SuiteAnalytics Connect, falling back to Fabric on a failed read).

### 2.5 Worker Pool

Three worker threads start with the app (`VIVE_WORKER_POOL_SIZE`). Each polls `jobs` and claims atomically (`web/queries.py:claim_next_pending_job()`). At most 2 concurrent Claude calls (`VIVE_MAX_CONCURRENT_AI_CALLS`, `src/ai/concurrency_limiter.py`); cache hits bypass the limit. A 30-minute cap stops a stuck PDF, and a heartbeat lets a job whose container died be retried (`web/worker.py`'s `_Heartbeat`). Graceful shutdown on SIGTERM/Ctrl+C.

---

## 3. Web Application — Routes

| Route | Purpose |
|---|---|
| `GET/POST /login`, `GET /logout` | Sign in/out |
| `GET /` | Home dashboard — KPI cards, active jobs, recent runs |
| `GET/POST /upload` | Upload PDFs — each becomes a job |
| `GET /exceptions`, `GET /exceptions/{vendor}` | Vendor cards; per-vendor exception detail (Accept / Dispute / Write off / Escalate) |
| `POST /exceptions/{vendor}/bulk-approve`, `/escalate`, `/accept-match`, `/undo-match` | Bulk approve, escalate, manual match and undo |
| `GET /netsuite-search` | Look up NetSuite records for a manual match |
| `GET /review-queue`, `GET /review-queue/{vendor}`, `POST .../action` | Low-confidence rows — approve or flag as exception |
| `GET /validation`, `GET /validation/{statement_id}` | Statements that failed validation, and why |
| `GET /jobs`, `GET /jobs/history`, `GET /jobs/{job_id}/extracted` | Active jobs (polled by the dashboard), upload history, extracted rows with View PDF |
| `GET /batches`, `GET /batches/{batch_id}` | Batches and per-file detail |
| `GET /reports`, `GET /reports/{statement_id}` | Reconciliation reports |
| `GET /statements/{document_hash}/pdf`, `GET /statements/{statement_id}/{filename}` | Serve the statement PDF |
| `GET /mailbox-sync`, `POST /mailbox-sync/*` | Manual mailbox sync (to blob / to web app / auto) |
| `POST /api/intake-trigger` | Event Grid webhook — validation handshake + BlobCreated events |
| `GET /users`, `POST /users/add`, `POST /users/remove` | User management |
| `GET /admin/netsuite-connect-check` | SuiteAnalytics Connect health check |

---

## 4. Intake

- **Upload page** — `/upload`.
- **Blob drop zone** — `viverecondropzone` / `incoming-statements`; Event Grid posts BlobCreated to `/api/intake-trigger` (shared secret, pinned container, event-count cap), which creates jobs under one `batch_id`.
- **Mailbox** — Logic Apps (`deploy/mailbox-logic-app/`, Terraform workspaces dev/prod) react to Graph notifications for instant intake. The 30-minute timer Function in `azure-functions/mailbox-sync` is switched off (`AUTO_SYNC_ENABLED`).

Infrastructure is Terraform under `deploy/` (App Service dev and prod, mailbox Logic App). State is local to each folder.

---

## 5. Exceptions

Matching writes one exception row per unmatched line to `silver.recon_exceptions` with an `exception_reason` — e.g. not found in NetSuite, amount mismatch, possible duplicate. AP users action them on the Exceptions page; dispositions go to `exception_dispositions`. `src/matching/engine.py` still supplies the confidence scoring helpers (`score_exception_confidence`, `score_overall_status`) the dashboard uses.

---

## 6. What Is Deliberately Not Built

- **AI judgment inside matching** — matching is always deterministic (Pass 3 is an allowed, unbuilt exception — see `docs/Claude.md` INV-02).
- **Full role-based permissions** — flat single-tier model is intentional.
- **Email alerts** — email provider not yet decided.

---

## 7. Known Gaps

| Gap | Notes |
|---|---|
| Fault isolation per file in a batch | `web/routers/intake_trigger.py` loops over events with no per-event `try/except`; one bad event can abort the rest of that delivery. |
| Local test failures | ~52 locally, all environment-specific (Azure credentials, missing local tables/PDFs, Tesseract, Windows file lock). |
