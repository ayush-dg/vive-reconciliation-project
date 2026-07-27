# ARCHITECTURE.md — VIVE Reconciliation
Updated: 2026-07-27

## Changelog
| Version | Date | Author | Change |
|---|---|---|---|
| v1.0 | 2026-07-24 | CD | Brownfield initial |
| v2.0 | 2026-07-27 | Ayush Kumar Sinha | Full update — parallel workers, batch intake, review queue, match confidence, routing/aging, bulk approve, all new routes and tables added |

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
| Infra | Data-access layer (connection.py — single place that selects SQLite vs Azure SQL), migration runners (SQLite + Azure SQL with ALTER TABLE support), AI client factory, audit logger, concurrency limiter. |

### 2.2 Data Model — Bronze/Silver/Gold

Bronze (raw AI extraction output) → **Silver** (`silver_reconciliation_standard` — canonical entity layer, typed/normalized, shared schema for both vendor-statement and ERP sides, distinguished only by `record_source`) → Gold (`gold_matched_invoices`, `gold_exceptions`, `gold_reconciliation_summary` — derived match/exception outcomes).

### 2.3 Backend

SQLite for local/dev/test; Azure SQL for production, selected automatically by whether `AZURE_SQL_SERVER` is set (`src/lakehouse/connection.py` is the single place that knows). Schema changes go through numbered migration files only — never hand-edited DDL. Azure SQL migration runner now supports ALTER TABLE for adding columns to existing tables (not just CREATE TABLE).

### 2.4 Extraction Chain

The whole PDF is sent to Claude Sonnet 4.6 as a native document. Column mapping is universal — no per-vendor configuration. pdfplumber + Tesseract OCR is the automatic fallback.

**Current active chain: Claude Sonnet 4.6 (Azure AI Foundry) → pdfplumber + OCR**

Chain history (each switch was driven by a live-tested reason):
1. Claude Haiku 4.5 (original)
2. Azure OpenAI gpt-5-mini (vendor consolidation)
3. Azure Document Intelligence prebuilt-layout (speed)
4. Claude Sonnet 4.6 (current — column-mapping quality on multi-invoice-column vendors)

Six providers remain registered in `src/ai/client_factory.py`; exactly one is active at a time via `config/ai/active_provider.json`'s `provider_chain[0]`.

### 2.5 Matching

A 2-level deterministic hierarchy (Level 1: exact invoice number; Level 2: RO number + amount), configurable tolerances. **Zero AI involvement by design.** Every match now also carries a `match_confidence` score (float 0.0–1.0) computed by the matching engine based on match type:

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

**Note:** the `PO` and `Fuzzy` rows are placeholder entries for match types not currently producible by `classify_match()` (there is no PO-based matching level, and the fuzzy-prefix level was deliberately removed) — see `discovery/components/C17_matching_engine.md`.

### 2.6 Worker Pool

Three concurrent worker threads start when the app starts (configurable via `VIVE_WORKER_POOL_SIZE`). Each worker polls Azure SQL atomically every 30 seconds. At most 2 concurrent Claude Sonnet calls at any time (`VIVE_MAX_CONCURRENT_AI_CALLS`, enforced via `src/ai/concurrency_limiter.py`). Cache hits bypass the semaphore. Graceful shutdown on SIGTERM/Ctrl+C.

---

## 3. Web Application — Routes

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

## 4. Database Tables (Azure SQL)

| Table | What it stores |
|---|---|
| `extraction_cache` | SHA-256 hash → row count. Prevents re-running AI on the same file. |
| `document_intake_log` | One row per PDF — vendor, period, extraction method, row counts, blob path. |
| `bronze_vendor_statement_raw` | Raw extracted invoice rows exactly as extracted. |
| `bronze_internal_erp_raw` | ERP invoice rows (currently Mock ERP; future: real NetSuite). |
| `silver_reconciliation_standard` | Normalized rows — vendor and ERP sides in one schema, `record_source` distinguishes them. |
| `gold_matched_invoices` | Matched invoice pairs with `match_confidence` score. |
| `gold_exceptions` | MISSING + AMOUNT_MISMATCH + EXTRACTION_INCOMPLETE + DUPLICATE_RECORD exceptions. Columns: `match_confidence`, `shop_owner`, `days_open` (computed, auto-updates daily), `escalation_status`, `escalated_at`, `escalated_by`. |
| `gold_reconciliation_summary` | Snapshot per run — totals, matched count, exception count, status. Dashboard KPIs live-query `gold_exceptions` instead. |
| `exception_dispositions` | Who actioned which exception, how (ACCEPTED/DISPUTED/WRITE_OFF), and when. |
| `validation_document_review_queue` | Rows flagged during extraction: MISSING_MANDATORY_FIELD or DUPLICATE_RECORD. |
| `jobs` | Job queue — PENDING → PROCESSING → COMPLETED/FAILED. Includes `batch_id`, `claim_token`. |
| `users` | Email, bcrypt-hashed password, created by, active status. |
| `ai_audit_log` | Every AI call — provider, model, latency, success/fail, interaction type. |

---

## 5. Auto-Intake (Blob Drop Zone) — Partial

**Built:**
- `viverecondropzone` Azure Storage account (West US 2, LRS)
- `incoming-statements` container as the drop zone
- `POST /api/intake-trigger` webhook — handles Event Grid validation handshake and BlobCreated events, downloads PDF, creates job with `batch_id`
- `batch_id` column on `jobs` table

**Blocked:**
- Event Grid System Topic creation requires Azure RBAC permissions not held by current account. Reported to Ashrith.
- App Service deployment (persistent public webhook URL) blocked on same subscription quota.

---

## 6. Exception Types

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

---

## 8. Known Gaps

| Gap | Notes |
|---|---|
| Live NetSuite integration | Biggest gap before real production value. Needs VIVE API credentials. |
| App Service deployment | Blocked on Ashrith's subscription quota. Files are ready. |
| Event Grid System Topic | Blocked on Azure RBAC permissions. |
| Stale job requeue | A job stuck PROCESSING past a timeout is never automatically re-queued. Tracked in original RISK_REGISTER as R-004. Now narrower — only stalls that one filename, not the whole queue. |
| Per-row genuine confidence from Claude Sonnet | Claude Sonnet currently returns 0.75 for all rows. Match confidence (a separate field) is now genuine; extraction confidence is still hardcoded. |
| GeminiClient/MistralClient confidence hardcoding | Both dormant — not in active chain. Still hardcode 0.75 confidence and lack totals-row filtering. Not a live risk. |
