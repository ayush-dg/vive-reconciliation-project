# VIVE Reconciliation — Implementation Context & Progress Tracker
Updated: 2026-08-06 (Fabric SQL database migration completed same day, see §10)

*This document is the complete context for the VIVE Reconciliation project. All phases through Phase 4 are complete. The system is now in active feature expansion (Steps 1-11 of the Final Plan). Read this fully before writing any code.*

---

## 0. How to Use This Document

- Status is always current as of the date above.
- Do not skip ahead without explicit instruction.
- Act as a senior data engineer: correctness, idempotency, never break what works.

---

## 1. What VIVE Reconciliation Is

A Python-based AI-powered AP automation tool for VIVE Collision (multi-shop auto body repair, ~79 shops, Northeast US). Vendors send monthly PDFs; the system extracts invoice data, compares against ERP records, surfaces discrepancies for the AP team. Replaces hours-long manual reconciliation.

---

## 2. Current State — What Is Built

### Core Pipeline (All Complete)
- **Four-stage pipeline**: document intake/extraction → mock ERP generation → deterministic matching → report generation (`notebooks/01_...` through `04_...`, orchestrated by `scripts/run_full_pipeline.py`)
- **Extraction**: Claude Sonnet 4.6 (Azure AI Foundry) primary → pdfplumber + Tesseract OCR fallback
- **Caching**: SHA-256 hash → `extraction_cache` lookup (cache hit requires `row_count > 0`)
- **Matching**: 2-level deterministic hierarchy (Level 1: exact invoice; Level 2: RO + amount), zero AI involvement, configurable tolerances
- **Match confidence**: Every match and exception now carries a `match_confidence` score (0.0–1.0), computed deterministically by match type
- **Row-level validation**: missing invoice ID or amount → `EXTRACTION_INCOMPLETE` exception; low confidence → `validation_document_review_queue`. Confidence threshold **raised from 0.60 to 0.90 on 2026-08-05** (engineer judgment call, not data-validated — see `INVARIANTS.md` INV-01 v1.4/v1.5 for full basis). Known consequence: `pdfplumber_fallback.py`'s row-confidence values (0.65 native, 0.50 OCR) were left unchanged, so all pdfplumber-fallback rows — OCR-derived or not — now route to review, not just the OCR ones.

### Web Application (FastAPI + Jinja2, not Streamlit)
- Home dashboard (4 KPI cards, active jobs, recent batches, reconciliation runs table)
- Upload PDF page (web UI upload → job queue → worker → dashboard update, confirmed working end-to-end)
- Exceptions page (vendor cards with live counts, oldest-open aging)
- Exception detail page (Accept / Dispute / Write off / Escalate, bulk approve for ≥0.99 confidence)
- Review queue page (Approve or Flag as exception for validation_document_review_queue rows)
- Batches page (auto-intake batches grouped by batch_id, manual uploads by date)
- Reports page, Users page, Settings (placeholder)

### Infrastructure
- Azure SQL (serverless free tier) as shared production database for most tables (Bronze, Silver, Gold, and four Recon-classified tables: jobs, exception_dispositions, users, ai_audit_log)
- **SQL database in Fabric cut-over (added 2026-08-05 as Fabric Warehouse; migrated 2026-08-06 to the correct item type):** three Recon-classified tables — `extraction_cache`, `document_intake_log`, `validation_document_review_queue` — route through `get_fabric_connection()`/`execute_sql_fabric()`/`execute_query_fabric()` in `src/lakehouse/connection.py` to a real **SQL database in Fabric** item (`FABRIC_SQLDB_ENDPOINT`/`FABRIC_SQLDB_NAME`). **Resolved gap:** these three tables now have real `IDENTITY(1,1)` columns — application code no longer computes `MAX(id) + 1`, closing `discovery/RISK_REGISTER.md` R-012 / `discovery/INVARIANT_CATALOGUE.md` IC-19 for these three specifically. 184 rows migrated (10/15/159, verified). Old Fabric Warehouse copies deliberately left in place as a rollback safety net, not dropped — decommissioning is a separate, not-yet-approved step. Bronze/Silver/Gold and the remaining four Recon tables (`jobs`, `exception_dispositions`, `users`, `ai_audit_log`) are not yet migrated to any Fabric item — R-012/IC-19 remain open for those. See `ARCHITECTURE.md` §2.3/§8 for the full current-state breakdown.
- Azure Blob Storage (vivereconciliation) for PDF archival
- Azure Blob Storage (viverecondropzone) as auto-intake drop zone
- 3-worker thread pool (configurable via VIVE_WORKER_POOL_SIZE)
- Atomic job claiming — no race conditions
- batch_id grouping on jobs table
- Per-user logins (bcrypt)
- Migration runner supports ALTER TABLE column additions for Azure SQL

### Exception Types
- MISSING — invoice on statement, not in ERP
- AMOUNT_MISMATCH — amount differs
- EXTRACTION_INCOMPLETE — missing invoice ID or amount on PDF
- DUPLICATE_RECORD — same invoice appeared more than once

### Routing & Aging
- `shop_owner` on `gold_exceptions` from `config/shop_owners.json`
- `days_open` computed column (auto-updates daily)
- Escalation: `escalation_status`, `escalated_at`, `escalated_by`

---

## 3. Final AI Extraction Decision

**Claude Sonnet 4.6, via Azure AI Foundry, is the extraction engine.** Whole-document streaming call. Column-agnostic mapping.

Chain history:
1. Claude Haiku 4.5 → Azure OpenAI gpt-5-mini (vendor consolidation) → Azure Document Intelligence prebuilt-layout (speed) → **Claude Sonnet 4.6 (current)**

**pdfplumber + Tesseract OCR** remains the last-resort fallback.

**Claude Haiku 4.5** is used only for the optional `--explain` narrative step (explanation_service.py), hardcoded and independent of provider_chain.

Fixed 2026-07-24: Claude Sonnet now returns a genuine, model-elicited per-row extraction confidence (previously a hardcoded 0.75 — see `discovery/RISK_REGISTER.md` R-001). `match_confidence` (separate field) is also genuine. Gemini/Mistral (both dormant) still hardcode 0.75.

---

## 4. Implementation Phases — Status

### Phase 1 — Foundation ✅ Complete
| Item | Status |
|---|---|
| Docker | Done |
| Rules doc (RULES.md) | Done |
| Migration tooling | Done |

### Phase 2 — Reliability ✅ Complete
| Item | Status |
|---|---|
| Disposition model | Done — exception_dispositions table, Accept/Dispute/Write off wired to web app |
| Audit log (human actions) | Done — disposed_by + disposed_at in exception_dispositions |
| Object storage (Blob) | Done — PDF archival to vivereconciliation, viverecondropzone drop zone created |

### Phase 3 — Multi-User Infrastructure ✅ Complete
| Item | Status |
|---|---|
| Real shared database (Azure SQL) | Done |
| Job queue + background worker | Done — 3-worker pool, atomic claiming, graceful shutdown |
| Per-user logins | Done — bcrypt, session-based auth |
| Shared hosting (App Service) | Blocked — Ashrith subscription quota pending |
| Reviewer dashboard | Done — FastAPI + Jinja2 (not Streamlit) |

### Phase 4 — Reliability Polish ✅ Complete
| Item | Status |
|---|---|
| Dependency-skip check (EXTRACTION_INCOMPLETE) | Done |
| Retry/truncation fix | Done |
| Config cleanup | Done |
| Azure SQL connection retry | Done |

---

## 5. Final Plan — Steps 1-11 Status

| Step | Description | Status |
|---|---|---|
| 1 | Blob drop zone (viverecondropzone, incoming-statements container) | ✅ Done |
| 2 | Event Grid trigger | ❌ Blocked — Azure RBAC (Ashrith) |
| 3 | batch_id grouping | ✅ Done — column on jobs, Batches page |
| 4 | Jobs from Event Grid | ✅ Code done — /api/intake-trigger built; untestable until Step 2 unblocked |
| 5 | Parallel workers (3-thread pool, AI rate limiting) | ✅ Done |
| 6 | Fault isolation per file | ❌ Not built |
| 7 | Match confidence score | ✅ Done |
| 8 | Routing + aging per exception | ✅ Done |
| 9 | Email alerts per batch | ⏳ Deferred — email provider not decided |
| 10 | Bulk approve high-confidence | ✅ Done |
| 11 | Batch summary UI | ✅ Done |

---

## 6. What NOT to Do

- Do not add AI judgment to matching — matching is always 100% deterministic.
- Do not re-add invoice number normalization/suffix stripping.
- Do not relax cache hit condition (row_count > 0).
- Do not build per-vendor column mapping.
- Do not expose mock ERP generator in the dashboard — CLI-only.
- Do not build live NetSuite integration — out of scope until VIVE provides API access.
- Do not use bare `load_dotenv()` in pipeline scripts — always use explicit path: `load_dotenv(os.path.join(PROJECT_ROOT, ".env"))`.
- Do not use two-step SELECT then UPDATE for job claiming — always use atomic claim query.

---

## 7. Open Items / Blockers

| Item | Notes |
|---|---|
| App Service deployment | Blocked on Ashrith's subscription quota |
| Event Grid System Topic | Blocked on Azure RBAC permissions (reported to Ashrith) |
| Email alerts (Step 9) | Email provider not decided — SendGrid vs Azure Communication Services vs SMTP |
| Tekion PDF vs Azure SQL | Never run through full pipeline against live database |
| Fault isolation (Step 6) | Not built — one failed file in batch could affect others |
| Genuine per-row extraction confidence | Fixed 2026-07-24 for Claude Sonnet (active primary). Gemini/Mistral (dormant) still hardcode 0.75 |
| Stale job requeue | Hung job for a given filename stalls that filename's future jobs — no auto-requeue |
| NetSuite integration | Needs VIVE API credentials — separate future project |

---

## 8. Key Bugs Fixed (Session Jul 22-27, 2026)

| Bug | Fix | Commit |
|---|---|---|
| Race condition — two workers claiming same job | Atomic job claiming with NOT EXISTS guard | dc7e64a |
| Azure SQL migration runner couldn't add columns | ALTER TABLE support added | 8668960 |
| Pipeline subprocess using SQLite not Azure SQL | Explicit load_dotenv path in all notebooks + scripts | 9c3e012 |
| Stale snapshot — exceptions page showed "Reconciled" despite open exceptions | Live-count via gold_exceptions instead of gold_reconciliation_summary snapshot | 65d89f8 |
| "Invoice #None" display | Template shows "Unknown" for null invoice_number | 88f383e |
| [FAIL] label for ROW_SKIP | Changed to [SKIP] in CLI report | 88f383e |
| AI Analysis (via None) on EXTRACTION_INCOMPLETE | Section hidden when ai_provider is null | 88f383e |
| fromisoformat crash on Azure SQL datetime objects | _days_since() handles both str and datetime | latest |
| Exceptions page missing vendors with no summary | get_vendor_summaries() unions gold_exceptions for summary-less vendors | b8f2c19 |
| Exceptions detail 500 for summary-less vendors | Fallback to derive metadata from gold_exceptions rows | f4c7b19 |
| Event Grid webhook had no authentication at all + container not pinned | Shared-secret auth (fail-closed) + container pinning + event-count cap — see RISK_REGISTER R-009 | 1fd1b6e |

---

## 9. Test Suite Status

- **Current (corrected 2026-08-06 — this figure was stale):** 281 passed / 18 failed / 299 total, verified by live run 2026-08-05. 17 of the 18 failures are local Azure-auth environment issues (Azure CLI auth blocked by this machine's Windows Application Control policy), 1 is the known Windows tempfile lock issue — not code defects. Supersedes the previous "189+ passing, 1 pre-existing Windows tempfile failure" figure, which predated this correction.
- Branch: phase-1-foundation (local only, never pushed) — not re-verified as part of this update

---

## 10. Progress Log

| Date | Item | Status change | Notes |
|---|---|---|---|
| 2026-07-13 | Docker | Not Started → Done | Dockerfile + docker-compose.yml verified end-to-end |
| 2026-07-13 | Rules doc | Not Started → Done | RULES.md with 11+ rules |
| 2026-07-13 | Migration tooling | Not Started → Done | schema_version + numbered migrations runner |
| 2026-07-14 | Azure OpenAI switch | Claude → gpt-5-mini | Vendor consolidation |
| 2026-07-14 | Document Intelligence switch | gpt-5-mini → DocIntel | Speed |
| 2026-07-15 | Phase 2: Disposition model | Not Started → Schema Done | exception_dispositions table |
| 2026-07-15 | Phase 2: Blob client | Not Started → Client Built | src/storage/blob_client.py |
| 2026-07-17 | Phase 3: Azure SQL | Not Started → Done | Shared production database |
| 2026-07-17 | Phase 3: Job queue + worker | Not Started → Done | Single worker initially |
| 2026-07-17 | Phase 3: Per-user logins | Not Started → Done | bcrypt auth |
| 2026-07-17 | Phase 3: Reviewer dashboard | Not Started → Done | FastAPI + Jinja2 (not Streamlit) |
| 2026-07-18 | Phase 4: Complete | Not Started → Done | EXTRACTION_INCOMPLETE, retry, config |
| 2026-07-19 | Claude Sonnet 4.6 switch | DocIntel → Claude Sonnet 4.6 | Column-mapping quality |
| 2026-07-19 | EXTRACTION_INCOMPLETE web UI | Done | Badge, detail page, fixes |
| 2026-07-22 | Race condition fix | Done | dc7e64a — atomic job claiming |
| 2026-07-22 | Azure SQL migration column support | Done | 8668960 |
| 2026-07-22 | Pipeline subprocess SQLite bug | Done | 9c3e012 — explicit load_dotenv path |
| 2026-07-22 | Exception resolution end-to-end | Verified | Accept tested, KPI + vendor card updated live |
| 2026-07-22 | Web upload end-to-end | Verified | Full path confirmed working |
| 2026-07-22 | Cosmetic fixes | Done | 88f383e |
| 2026-07-23 | Review queue UI | Done | a4f9b23 |
| 2026-07-23 | Exceptions page for summary-less vendors | Done | b8f2c19, f4c7b19 |
| 2026-07-23 | Blob drop zone | Done | viverecondropzone + incoming-statements |
| 2026-07-24 | /api/intake-trigger webhook | Done | 3a8f291 |
| 2026-07-24 | Parallel worker pool (Step 5) | Done | e7f2c15 |
| 2026-07-23 | Batch summary UI (Step 11) | Done | 2d4f891 |
| 2026-07-24 | Match confidence scoring (Step 7) | Done | |
| 2026-07-23 | Routing + aging (Step 8) | Done | |
| 2026-07-23 | Bulk approve (Step 10) | Done | |
| 2026-07-23 | datetime handling bug fix | Done | |
| 2026-08-05 | Fabric Warehouse cut-over | Not Started → Partial | `extraction_cache`, `document_intake_log`, `validation_document_review_queue` routed to Fabric Warehouse via `get_fabric_connection()`/`execute_sql_fabric()`/`execute_query_fabric()`. Remaining Recon tables + Bronze/Silver/Gold still on Azure SQL/SQLite. Known gap: no IDENTITY column, `MAX(id)+1` not concurrency-safe — R-012/IC-19 |
| 2026-08-05 | INV-01 confidence threshold | 0.60 → 0.90 | Engineer judgment call, not data-validated — propagated repo-wide; 281/18/299 test re-run confirmed no regression. pdfplumber-fallback rows (0.65/0.50) deliberately left unchanged, now all route to review |
| 2026-08-05 | Test suite count | 189+ passing (stale) → 281 passed / 18 failed / 299 total | Corrected via live run; all 18 failures are local-environment issues, not code defects |
| 2026-08-06 | This document | Refreshed | Confidence threshold, Fabric cut-over, and test count brought current — this file had gone stale relative to `ARCHITECTURE.md`/`Claude.md`/`INVARIANTS.md`, all updated 2026-08-05 |
| 2026-08-06 | Fabric cut-over | Fabric Warehouse → real SQL database in Fabric | `extraction_cache`/`document_intake_log`/`validation_document_review_queue` repointed to a genuine SQL database in Fabric item (`FABRIC_SQLDB_ENDPOINT`/`FABRIC_SQLDB_NAME`), real `IDENTITY(1,1)` primary keys — R-012/IC-19 resolved for these three tables. 184 rows migrated (10/15/159, verified before/after). Old Warehouse copies left in place, not dropped. Remaining Recon tables + Bronze/Silver/Gold still unmigrated |
