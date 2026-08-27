# ARCHITECTURE.md — VIVE Reconciliation
Updated: 2026-08-06

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

---

## 1. What This System Is

VIVE Reconciliation is a Python-based AI-powered accounts payable automation tool built for VIVE Collision, a multi-shop auto body repair company (~79 shops, Northeast US). Vendor suppliers send monthly PDF statements; the system extracts line-item data from each PDF, compares it against VIVE's ERP records, and surfaces discrepancies for the AP team to review — replacing a manual, hours-long per-vendor cross-check.

**It does not itself approve, reject, or execute payments** — it identifies discrepancies for a human to act on.

---

## 2. Shape of the System

A 7-stage pipeline, run via numbered scripts (`notebooks/01_...` through `04_...`, orchestrated by `scripts/run_full_pipeline.py`), with a FastAPI web application wrapping the whole thing for multi-user access.

### 2.1 Layers

| Layer | What lives here |
|---|---|
| Serving | FastAPI + Jinja2 web app. 10 routers: auth, dashboard, exceptions, jobs, reports, review_queue, upload, users, batches, intake_trigger. Server-rendered, no client-side SPA. |
| Pipeline | Extraction (Claude Sonnet 4.6 primary + pdfplumber/OCR fallback), matching engine, mock ERP generator, invoice normalization, background job worker pool (3 workers). |
| Infra | Data-access layer (connection.py — single place that selects SQLite vs Fabric/Azure SQL target), migration runners, AI client factory, audit logger, concurrency limiter. **Storage now spans three Fabric item types (Lakehouse, Warehouse, SQL database in Fabric) instead of a single Azure SQL Database — see §2.3.** |

### 2.2 Data Model — Bronze / Silver / Gold / Recon

Bronze (raw AI extraction output) → **Silver** (`silver_reconciliation_standard` — canonical entity layer, typed/normalized, shared schema for both vendor-statement and ERP sides, distinguished only by `record_source`) → Gold (`gold_matched_invoices`, `gold_exceptions`, `gold_reconciliation_summary` — derived match/exception outcomes).

**v2.1 change:** these three layers are no longer three schemas inside one Azure SQL Database. Each now sits on the Fabric item built for its actual access pattern:

| Layer | Fabric item | Why |
|---|---|---|
| **Bronze** | **Fabric Lakehouse** | Append-only, rebuildable, raw extraction output — exactly what Lakehouse (Delta tables) is for. |
| **Silver** | **Fabric Warehouse** | Typed/normalized reporting-shaped data, queried by matching and reporting jobs — Warehouse's big-scan SQL engine suits this better than Lakehouse. |
| **Gold** | **Fabric Warehouse** | Derived match/exception aggregates for reporting and dashboards. Same engine as Silver, same reasoning. |
| **Recon** *(new)* | **SQL database in Fabric** | The live operational/workflow state — jobs, exceptions, dispositions, review queue, audit log — carries real financial consequences (who approved what, when). This needs enforced foreign keys and row-level concurrency control, which Lakehouse/Warehouse do not provide. SQL database in Fabric is the same transactional engine as Azure SQL Database, provisioned as a native Fabric item, and it auto-mirrors into OneLake so reporting can still read it. **Bronze/Silver/Gold are safe to rebuild; Recon must never be rebuilt — that distinction is why it sits on its own item type.** |

### 2.3 Backend

SQLite for local/dev/test, unchanged. The **target** layout for production is the single Azure SQL Database split across Fabric as follows:

- **Bronze tables** (`bronze_vendor_statement_raw`, `bronze_internal_erp_raw`) → **Fabric Lakehouse**
- **Silver table** (`silver_reconciliation_standard`) → **Fabric Warehouse**
- **Gold tables** (`gold_matched_invoices`, `gold_exceptions`, `gold_reconciliation_summary`) → **Fabric Warehouse**
- **Recon / operational tables** (`jobs`, `exception_dispositions`, `validation_document_review_queue`, `ai_audit_log`, `extraction_cache`, `document_intake_log`, `users`) → **SQL database in Fabric**

**Actual current state (corrected 2026-08-06 — see changelog v2.5):** three of the seven Recon-classified tables are cut over — `extraction_cache`, `document_intake_log`, and `validation_document_review_queue` — via `get_fabric_connection()`/`execute_sql_fabric()`/`execute_query_fabric()` in `src/lakehouse/connection.py:75-119,255-289`. **These now correctly target a real "SQL database in Fabric" item** (`FABRIC_SQLDB_ENDPOINT`/`FABRIC_SQLDB_NAME`), matching the target bullet above exactly — repointed from Fabric Warehouse on 2026-08-06. SQL database in Fabric provides real `IDENTITY(1,1)` primary keys, so **the R-012/IC-19 concurrency gap (`MAX(id) + 1` computed in application code) is resolved for these three tables specifically** — the engine assigns ids now, not application code. Schema created via `scripts/create_fabric_sqldb_schema.py`; 184 existing rows migrated via `scripts/migrate_fabric_data_to_sqldb.py`, verified by direct `COUNT(*)` before and after (10/15/159, unchanged). The old Fabric Warehouse copies were deliberately left in place as a rollback safety net, not dropped.

The remaining four Recon-classified tables (`jobs`, `exception_dispositions`, `users`, `ai_audit_log`) and all of Bronze/Silver/Gold are **still unmigrated** — they remain on Azure SQL/SQLite via the original `get_connection()`/`execute_sql()`/`execute_query()` path, and R-012/IC-19 remain open for any future cut-over of those tables specifically. `src/lakehouse/connection.py` therefore currently has two live paths side by side, not the single layer-routed design the target bullets above describe. Schema changes still go through numbered migration files only, never hand-edited DDL — the Fabric side now has a tracked provisioning mechanism for these three tables (`scripts/create_fabric_sqldb_schema.py`, deliberately not a `migrations/` file — see R-006 and that script's docstring), but no equivalent exists yet for the remaining four Recon tables or Bronze/Silver/Gold.

### 2.4 Extraction Chain

Unchanged by this migration. The whole PDF is sent to Claude Sonnet 4.6 as a native document. Column mapping is universal — no per-vendor configuration. pdfplumber + Tesseract OCR is the automatic fallback.

**Current active chain: Claude Sonnet 4.6 (Azure AI Foundry) → pdfplumber + OCR** — verified 2026-08-05 by direct code trace + live test run (Claude Code), not by config file or docstring alone:
- `config/ai/active_provider.json` → `provider_chain: ["claude_sonnet", "pdfplumber"]`. Runtime call traced to `document_understanding_engine.py:200-204` → `client_factory.py` → `claude_sonnet_client.py` (`config/ai/claude_sonnet_extraction.json`, model `claude-sonnet-4-6`). Azure Document Intelligence is registered in `client_factory.py` but is **not** in the active chain and is never called from the extraction path.
- **pytesseract OCR is confirmed actively wired into the pdfplumber fallback**, not just present in `requirements.txt`:
  - `src/ai/ocr_extractor.py` — lazy-imports `pytesseract` inside `is_ocr_available()` (line 46), `ocr_page()` (line 66), `extract_text_with_ocr()` (line 86); actual calls at lines 39 (`tesseract_cmd` path config), 50 (`get_tesseract_version()`), 74 and 103 (`image_to_string()`).
  - `src/ai/pdfplumber_fallback.py:49` imports `is_ocr_available` and `ocr_page` from `ocr_extractor.py`. Per `extract_with_pdfplumber()` run: `is_ocr_available()` is checked once (line 50); when a page's native text layer falls under a 500-char threshold (`OCR_TRIGGER_TEXT_THRESHOLD`, line 33), `_try_ocr_page()` calls `ocr_page_fn()` (line 314), which runs `pytesseract.image_to_string()`. The OCR output is converted to a pseudo-table (`_ocr_text_to_pseudo_table`, line 340) and fed through the same column-mapping pipeline as native pdfplumber tables.
  - OCR-derived rows are deliberately scored lower (`line_confidence = 0.50` vs. 0.65 for native pdfplumber rows, line 113) — both now below the **0.90** validation threshold (raised 2026-08-05 from 0.60, see INVARIANTS.md INV-01 v1.4), so **all pdfplumber-fallback rows, OCR-derived or not, route to human review rather than auto-passing.** Prior to the threshold amendment, non-OCR pdfplumber rows (0.65) cleared the gate and OCR rows (0.50) did not — that distinction no longer changes the gate outcome; the 0.65/0.50 split is retained only as a relative-reliability signal for reviewers, not a pass/fail line.
  - **Dead code found:** `extract_text_with_ocr()` (`ocr_extractor.py:77-108`, whole-document OCR) has no callers anywhere in `src/` — only `is_ocr_available` and `ocr_page` are imported from that module. `RULES.md` (RULE-10, lines 311–313) describes an older state where OCR output had no consumer; that is no longer true — `ocr_page()` is fully wired, `extract_text_with_ocr()` specifically is the unused leftover.
- Claude Haiku 4.5 (`config/ai/claude.json`) is used only for `--explain` narrative output (`explanation_service.py`) — a separate call path, never invoked for line-item extraction.

Chain history (each switch was driven by a live-tested reason):
1. Claude Haiku 4.5 (original)
2. Azure OpenAI gpt-5-mini (vendor consolidation)
3. Azure Document Intelligence prebuilt-layout (speed)
4. Claude Sonnet 4.6 (current — column-mapping quality on multi-invoice-column vendors)

Six providers remain registered in `src/ai/client_factory.py`; exactly one is active at a time via `config/ai/active_provider.json`'s `provider_chain[0]`.

### 2.5 Matching

Unchanged by this migration. A 2-level deterministic hierarchy (Level 1: exact invoice number; Level 2: RO number + amount), configurable tolerances. **Zero AI involvement by design.** Every match carries a `match_confidence` score (float 0.0–1.0) computed by the matching engine based on match type:

| Match type | Score |
|---|---|
| Exact invoice + exact amount | 1.00 |
| Exact invoice + within tolerance | 0.95 |
| Exact invoice + amount mismatch | 0.70 |
| PO number + exact amount | 0.85 |
| RO number + exact amount | 0.80 |
| Fuzzy/fallback | 0.60 |
| MISSING exception | 0.90 |
| AMOUNT_MISMATCH exception | 0.85 |
| EXTRACTION_INCOMPLETE exception | 0.50 |

**Note:** the `PO` and `Fuzzy` rows are placeholder entries for match types not currently producible by `classify_match()` (there is no PO-based matching level, and the fuzzy-prefix level was deliberately removed) — see `discovery/components/C17_matching_engine.md`. Match rows themselves now live in Gold (Fabric Warehouse); the matching engine reads Silver (Fabric Warehouse) and writes results there — see §2.2.

### 2.6 Worker Pool

Unchanged by this migration. Three concurrent worker threads start when the app starts (configurable via `VIVE_WORKER_POOL_SIZE`). Each worker polls the job queue atomically every 30 seconds — **the job queue (`jobs` table) now lives in the Recon layer (SQL database in Fabric), not Azure SQL directly, so polling needs the connection-layer routing change in §2.3 before this keeps working in production.** At most 2 concurrent Claude Sonnet calls at any time (`VIVE_MAX_CONCURRENT_AI_CALLS`, enforced via `src/ai/concurrency_limiter.py`). Cache hits bypass the semaphore. Graceful shutdown on SIGTERM/Ctrl+C.

---

## 3. Web Application — Routes

Unchanged by this migration.

| Route | Purpose |
|---|---|
| `GET /` | Home dashboard — 4 KPI cards, active jobs, recent batches, reconciliation runs table |
| `GET/POST /upload` | Upload PDFs — each becomes a job in the queue |
| `GET /exceptions` | Vendor cards with exception counts and oldest-open aging |
| `GET /exceptions/{vendor}` | Exception detail — Accept / Dispute / Write off / Escalate per exception. Bulk approve button for ≥0.99 confidence. |
| `POST /exceptions/{vendor}/bulk-approve` | Approve all open exceptions meeting confidence threshold |
| `POST /exceptions/{vendor}/escalate` | Mark exception as escalated |
| `GET /review-queue` | Vendor cards for validation_document_review_queue |
| `GET /review-queue/{vendor}` | Per-row Approve or Flag as exception |
| `POST /review-queue/{vendor}/action` | Approve or flag a specific review queue row |
| `GET /batches` | All batches (auto-intake grouped by batch_id, manual uploads grouped by date) |
| `GET /batches/{batch_id}` | Per-file detail within a batch |
| `GET /reports` | All reconciliation runs with links to reports |
| `GET /users` | User management |
| `POST /api/intake-trigger` | Event Grid webhook — validation handshake + BlobCreated events |
| `GET /jobs` | Active jobs API endpoint (polled by dashboard JS) |

---

## 4. Database Tables — grouped by Fabric layer (v2.1)

### Bronze — Fabric Lakehouse
| Table | What it stores |
|---|---|
| `bronze_vendor_statement_raw` | Raw extracted invoice rows exactly as extracted. |
| `bronze_internal_erp_raw` | ERP invoice rows (currently Mock ERP; future: real NetSuite). |

### Silver — Fabric Warehouse
| Table | What it stores |
|---|---|
| `silver_reconciliation_standard` | Normalized rows — vendor and ERP sides in one schema, `record_source` distinguishes them. |

### Gold — Fabric Warehouse
| Table | What it stores |
|---|---|
| `gold_matched_invoices` | Matched invoice pairs with `match_confidence` score. |
| `gold_exceptions` | MISSING + AMOUNT_MISMATCH + EXTRACTION_INCOMPLETE + DUPLICATE_RECORD exceptions. Columns: `match_confidence`, `shop_owner`, `days_open` (computed, auto-updates daily), `escalation_status`, `escalated_at`, `escalated_by`. |
| `gold_reconciliation_summary` | Snapshot per run — totals, matched count, exception count, status. Dashboard KPIs live-query `gold_exceptions` instead. |

### Recon — SQL database in Fabric (new grouping, v2.1)
| Table | What it stores |
|---|---|
| `extraction_cache` | SHA-256 hash → row count. Prevents re-running AI on the same file. |
| `document_intake_log` | One row per PDF — vendor, period, extraction method, row counts, blob path. |
| `exception_dispositions` | Who actioned which exception, how (ACCEPTED/DISPUTED/WRITE_OFF), and when. |
| `validation_document_review_queue` | Rows flagged during extraction: MISSING_MANDATORY_FIELD or DUPLICATE_RECORD. |
| `jobs` | Job queue — PENDING → PROCESSING → COMPLETED/FAILED. Includes `batch_id`, `claim_token`. |
| `users` | Email, bcrypt-hashed password, created by, active status. |
| `ai_audit_log` | Every AI call — provider, model, latency, success/fail, interaction type. |

**Rationale for this grouping:** these seven tables are exactly the ones with live financial/operational consequences (who did what, when, and to which job) — the same reasoning the target-state VIVE Statement Reconciliation architecture (v3.1) uses to keep its `recon` schema off Lakehouse/Warehouse. They need real FK enforcement and row-level concurrency (e.g. two AP users bulk-approving overlapping exception sets), which Lakehouse/Warehouse don't guarantee. Bronze/Silver/Gold, by contrast, are all safely rebuildable from source.

---

## 5. Auto-Intake (Blob Drop Zone) — Partial

Unchanged by this migration.

**Built:**
- `viverecondropzone` Azure Storage account (West US 2, LRS)
- `incoming-statements` container as the drop zone
- `POST /api/intake-trigger` webhook — handles Event Grid validation handshake and BlobCreated events, downloads PDF, creates job with `batch_id`
- `batch_id` column on `jobs` table
- **Security fix (2026-07-25):** webhook was unauthenticated end-to-end until this date; now fixed in code (shared secret, pinned container, event-count cap) — see `discovery/RISK_REGISTER.md` R-009

**Blocked:**
- Event Grid System Topic creation requires Azure RBAC permissions not held by current account. Reported to Ashrith.
- App Service deployment (persistent public webhook URL) blocked on same subscription quota.
- **New (v2.1):** Fabric workspace provisioning and item-level permissions (Lakehouse, Warehouse, SQL database in Fabric) also require RBAC not yet confirmed as held — flag to Ashrith alongside the existing Event Grid / App Service asks.

---

## 6. Exception Types

Unchanged by this migration.

| Type | Meaning | Confidence |
|---|---|---|
| MISSING | Invoice on vendor statement, not found in ERP | 0.90 |
| AMOUNT_MISMATCH | Invoice exists in both, amounts differ | 0.85 |
| EXTRACTION_INCOMPLETE | Row skipped — no invoice ID or no amount found on PDF | 0.50 |
| DUPLICATE_RECORD | Same invoice + amount appeared more than once in PDF | N/A |

---

## 7. What Is Deliberately Not Built

- **Live NetSuite integration** — not scoped until VIVE grants API access.
- **Per-vendor onboarding/configuration** — universal column mapping is deliberate.
- **AI judgment inside matching** — matching is always 100% deterministic.
- **Full role-based permissions** — flat single-tier model is intentional.
- **Email alerts** — email provider not yet decided (Step 9, deferred).
- **Fault isolation per file in a batch** — not yet built (Step 6).
- **Settings page functionality** — placeholder, build when VIVE specifies needs.
- **Fabric migration — partially cut over, not deliberately-unbuilt (v2.1, corrected 2026-08-06)** — this document describes the *target* storage layout for Bronze/Silver/Gold/Recon. Three Recon-classified tables (`extraction_cache`, `document_intake_log`, `validation_document_review_queue`) are cut over, to a real **SQL database in Fabric** item — the correct target item type, since 2026-08-06 (was Fabric Warehouse). The remaining four Recon tables and all of Bronze/Silver/Gold are not yet migrated — `connection.py`'s original Azure SQL/SQLite path still serves them, and the worker-pool `jobs` table specifically is one of the four not yet migrated. See §2.3 and §8 for the full current-state breakdown.

---

## 8. Known Gaps

| Gap | Notes |
|---|---|
| **Fabric migration — 3 of 7 Recon tables done and on the correct item type (updated 2026-08-06)** | This document (v2.1) describes the target layout — Bronze on Lakehouse, Silver/Gold on Warehouse, Recon on SQL database in Fabric. `extraction_cache`, `document_intake_log`, and `validation_document_review_queue` are cut over via `get_fabric_connection()`/`execute_sql_fabric()`/`execute_query_fabric()` (`src/lakehouse/connection.py:75-119,255-289`) to a real **SQL database in Fabric** item (`FABRIC_SQLDB_ENDPOINT`/`FABRIC_SQLDB_NAME`) — repointed 2026-08-06 from Fabric Warehouse, which resolves the R-012/IC-19 IDENTITY/concurrency gap for these three tables specifically (real `IDENTITY(1,1)` columns now, no more application-level `MAX(id)+1`). 184 rows migrated, verified by `COUNT(*)` (10/15/159). Old Warehouse copies deliberately left in place, not dropped, pending a separate decommissioning decision. `jobs`, `exception_dispositions`, `users`, `ai_audit_log`, and all of Bronze/Silver/Gold still target a single Azure SQL Database (or SQLite locally) via the original `get_connection()`/`execute_sql()`/`execute_query()` path — R-012/IC-19 remain open for these. Migration runners and the worker poll loop are likewise unchanged. Completing the rest of the migration is still a dedicated effort; see the Claude Code prompt below. |
| Live NetSuite integration | Biggest gap before real production value. Needs VIVE API credentials. |
| App Service deployment | Blocked on Ashrith's subscription quota. Files are ready. |
| Event Grid System Topic | Blocked on Azure RBAC permissions. |
| Fabric workspace / item permissions | New, v2.1. **Updated 2026-08-06:** confirmed NOT blocked, at least for the identity used in this session — live check via the Fabric REST API showed Admin role on the workspace, and a new SQL database item was successfully created. Any remaining doubt is about who else besides that identity holds equivalent access, not whether Fabric-workspace-level permissions are held at all. |
| Stale job requeue | A job stuck PROCESSING past a timeout is never automatically re-queued. Tracked in original RISK_REGISTER as R-004. Now narrower — only stalls that one filename, not the whole queue. |
| Per-row genuine confidence from Claude Sonnet | Fixed 2026-07-24 — Claude Sonnet now returns genuine per-row confidence (see `discovery/RISK_REGISTER.md` R-001). Gemini/Mistral remain broken (still hardcoded at 0.75) but dormant. |
| GeminiClient/MistralClient confidence hardcoding | Both dormant — not in active chain. Still hardcode 0.75 confidence and lack totals-row filtering. Not a live risk. |
| `extract_text_with_ocr()` dead code | `ocr_extractor.py:77-108` — whole-document OCR function has no callers anywhere in `src/`. The wired path uses `ocr_page()` (per-page) instead. Safe to remove or leave; not a live risk either way. |
| Test suite Azure-auth failures (local only) | 17 of 18 current failures are `AZURE_SQL_SERVER` forcing a real Azure CLI token fetch, blocked by this machine's Windows Application Control policy (`pymsalruntime` DLL blocked). Environment-specific, not a code defect — will not reproduce on a machine/CI runner with working Azure CLI auth or with `AZURE_SQL_SERVER` unset for local runs. |

---

## 9. Claude Code prompt — completing the Fabric migration

This document describes the target state. **Updated 2026-08-06:** three Recon-classified tables are done and on the correct item type — `extraction_cache`, `document_intake_log`, `validation_document_review_queue` now live on a real SQL database in Fabric item, repointed from Fabric Warehouse, R-012/IC-19 resolved for these three (see §2.3, §8). What's left is the remaining four Recon tables and all of Bronze/Silver/Gold. To complete the rest of the migration, paste this into a Claude Code session:

```
Context: VIVE Reconciliation currently uses a single Azure SQL Database (with SQLite for local dev) for Bronze, Silver, Gold, and four operational tables (jobs, exception_dispositions, users, ai_audit_log), selected via get_connection()/execute_sql()/execute_query() in src/lakehouse/connection.py. Three operational tables (extraction_cache, document_intake_log, validation_document_review_queue) are already correctly cut over to a real SQL database in Fabric item via a separate path — get_fabric_connection()/execute_sql_fabric()/execute_query_fabric() — with real IDENTITY columns, resolving R-012/IC-19 for those three specifically (as of 2026-08-06).

Task: Update the data-access layer to route by table group instead of a single backend switch, extending the pattern already proven for the three Recon tables done above:
- Bronze tables (bronze_vendor_statement_raw, bronze_internal_erp_raw) → Fabric Lakehouse
- Silver table (silver_reconciliation_standard) → Fabric Warehouse
- Gold tables (gold_matched_invoices, gold_exceptions, gold_reconciliation_summary) → Fabric Warehouse
- Remaining operational/Recon tables (jobs, exception_dispositions, users, ai_audit_log) → SQL database in Fabric — the same item already created for extraction_cache/document_intake_log/validation_document_review_queue, or a decision to use a separate item; confirm with the engineer first

Requirements:
1. Do not change SQLite local/dev behavior — this is a production-only routing change.
2. src/lakehouse/connection.py should expose a way to get the correct connection/client per table group, not just a single "is Azure SQL configured" boolean. The existing get_fabric_connection()/execute_sql_fabric()/execute_query_fabric() functions and their schema-creation script (scripts/create_fabric_sqldb_schema.py) are the proven pattern to extend, not replace.
3. Every existing caller of the connection layer must be updated to pass or infer which table group it's reading/writing, without changing its own business logic.
4. Migration runners need to target three separate Fabric items instead of one Azure SQL Database — do not merge them into one migration file, and do not put Fabric-targeted T-SQL DDL inside migrations/ itself (that broke the SQLite test-suite migration runner during the three-table cut-over — see scripts/create_fabric_sqldb_schema.py's docstring for why).
5. Flag, but do not attempt to fix, anything that assumes cross-table-group transactions (e.g. a single SQL transaction spanning a Bronze write and a Recon write) — that will need explicit handling since Lakehouse/Warehouse and SQL database in Fabric are different engines.
6. Do not touch the extraction chain, matching engine, or worker pool concurrency logic — only the storage routing.

Before writing code, list every file that currently imports or calls into src/lakehouse/connection.py (including get_fabric_connection()/execute_sql_fabric()/execute_query_fabric() callers), and confirm the plan with me before making changes.
```