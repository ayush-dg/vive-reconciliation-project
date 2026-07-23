# INTAKE_SUMMARY.md — VIVE Reconciliation
**Date:** 2026-07-23
**Engineer:** Ayush Kumar Sinha
**Path:** A — Custodian
**Canonical layer boundary:** Silver layer (`silver_reconciliation_standard`) — the shared normalized schema both vendor-statement and internal-ERP records conform to, distinguished only by `record_source` (`VENDOR_STATEMENT` vs `INTERNAL_ERP`). Confirmed by engineer 2026-07-23 over the alternative (Gold layer) — Silver is where "Invoice" exists as a business entity prior to match-outcome derivation.
**Session F disposition:** FULL EXTRACTION — no maintained metadata catalog (AWS Glue / Unity Catalog / Collibra / Alation / Apache Atlas / equivalent) is in use; a data layer exists structurally via numbered SQL migrations (`migrations/001_initial_schema.sql`, `002_exception_dispositions.sql`, `003_add_blob_storage_path.sql`) plus `src/lakehouse/migrations.py` (SQLite) and `src/lakehouse/azure_sql_migrations.py` (Azure SQL).

## System Purpose

VIVE Reconciliation is a Python-based tool built for VIVE Collision, a multi-shop auto body repair company (~79 shops, Northeast US). Vendor suppliers (parts distributors, sublet shops, towing companies) send monthly PDF statements. VIVE extracts the data from each PDF, compares it against VIVE's ERP records, and surfaces discrepancies for the AP team to review — replacing what used to be an hours-long manual cross-check per vendor. The system identifies discrepancies for human review; it does not approve, reject, or execute payments itself.

## Known Architecture

- **Four-stage pipeline**, run via numbered scripts (`notebooks/01_...` through `04_...`): document intake/extraction → mock ERP generation → deterministic matching → report generation. Containerized via Docker for reproducible execution.
- **Extraction chain (per RULES.md RULE-04, superseded twice):** Azure Document Intelligence (`prebuilt-layout`, whole PDF in one call) primary, deterministic pdfplumber + Tesseract OCR fallback. Column mapping is universal (no per-vendor config), done via shared keyword-matching logic (`_find_header_row`/`_map_columns`/`_extract_invoice_row`). History: Claude (Haiku 4.5) → Azure OpenAI gpt-5-mini → Azure Document Intelligence, each switch driven by a live-tested reason (vendor consolidation, then raw speed), not accuracy regression.
- **Extraction caching:** SHA-256 hash of every PDF checked against `extraction_cache`; a hit requires `row_count > 0` from a prior successful run (RULE-02, deliberately not relaxed).
- **Matching engine:** 2-level deterministic hierarchy (Level 1: exact invoice number; Level 2: RO number + amount), configurable tolerances in `config/matching/matching_rules.json`. Zero AI involvement by design (RULE-03) — treated as a hard invariant.
- **Invoice number handling:** stored exactly as extracted, whitespace-trimmed only, no suffix/prefix stripping or fuzzy-prefix matching (RULE-01, RULE-11 — both previously tried and deliberately reverted after they hid real discrepancies).
- **Bronze/Silver/Gold lakehouse layering:** Bronze (raw AI output) → Silver (`silver_reconciliation_standard`, typed/normalized, shared schema for vendor and ERP sides, `record_source` column distinguishes them) → Gold (`gold_matched_invoices`, `gold_exceptions`, `gold_reconciliation_summary`).
- **Mock ERP placeholder (RULE-06):** Internal ERP data is simulated by `src/mock_erp/generator.py` because live NetSuite API access is not yet available. Deliberately CLI-only (RULE-05) — must never be wired into the dashboard. The eventual real-NetSuite swap is scoped to be narrow because both sides already share the Silver schema.
- **Backend:** `src/lakehouse/connection.py` selects Azure SQL (via `pyodbc`) if `AZURE_SQL_SERVER` is set, else SQLite — the single place that knows the storage backend (RULE-13). Schema changes are numbered migration files only, never hand-edited DDL (RULE-12).
- **Planned/in-progress (per Implementation Context Phase 2-3):** disposition model (`exception_dispositions`, schema done, report-generation suppression logic not yet wired), Blob Storage retention (client built, not yet wired into the pipeline), job queue + background worker (not started), per-user logins (not started, deliberately flat permission model — no Admin/Reviewer tiers, RULE-08), Streamlit reviewer dashboard (not started).
- **Explicitly out of scope / will not be built:** live NetSuite integration until access is granted; per-vendor onboarding/config; AI judgment inside matching; full role-based permissions; document-level confidence gate and AI "looks odd" advisory flag (both deferred behind specific trigger conditions, RULE-09).

## Known Pain Points

- Report-generation logic that looks up whether an exception was already resolved (via `exception_dispositions`) is schema-complete but **not yet wired into the report generation flow** (Implementation Context Phase 2 table, and Progress Log 2026-07-15).
- Blob Storage client is built but **not yet wired into the pipeline**; `azure-storage-blob` not yet added to `requirements.txt` (consistent with `azure-ai-documentintelligence` also being absent despite being lazily imported).
- Job queue + background worker is called out as "the one genuine gap" for real multi-user use (Implementation Context Section 6).
- `pdfplumber`'s confidence score is acknowledged in its own docs as fake/manual (0.65 if table-like rows found, 0.20 if not) — not a genuine quality signal, relevant to anyone touching validation logic.
- One pre-existing test failure: `test_ai_clients.py::TestClaudeClient::test_generate_with_file_parses_json` — documented as a Windows file-locking quirk, unrelated to the active provider chain.
- `azure_openai_client.py` and its gpt-5-mini/nano/5.1 configs remain in the repo, registered for direct access, but out of the active `provider_chain` pending a separate cleanup pass — extraction should confirm whether anything still actually calls them.
- Two pytest test files (`test_document_understanding_engine.py`, `test_explanation_service.py`) mock the AI client but not `audit_logger.log_ai_call`, so every test run writes real rows into `ai_audit_log` — a known, accepted quirk, not a defect.
- Config cleanup (moving hardcoded confidence threshold and provider-specific trim limits into config) is listed as Not Started (Phase 4).

## Documents Reviewed

- `RULES.md` — 13 numbered deliberate-decision rules (invoice number handling, cache semantics, matching determinism, extraction provider chain history, mock ERP CLI-only boundary, NetSuite placeholder, universal column mapping, flat permission model, deferred Phase 5 triggers, OCR confidence tagging, no fuzzy-prefix matching, migration discipline, Azure SQL/SQLite backend split), each with an enforcement-point file reference.
- `docs/VIVE_Implementation_Context.md` — living implementation tracker: system purpose, current pipeline state, final AI extraction decision and its history, phased implementation plan (1-5) with status per item, explicit "do not build" guardrails, a Scrutin-comparison coverage table, cost summary, and a dated Progress Log of every status change through 2026-07-15.
- `docs/VIVE_Scope_Final_Architecture (1).pdf` — formal scope document (final target architecture): project overview, in-scope/out-of-scope lists, assumptions, deliverables, stakeholders, constraints. States Claude (Haiku 4.5) as the AI extraction decision — since superseded twice per RULES.md RULE-04; PDF not updated to reflect this.
- `docs/VIVE_Improvement_Plan_Simple (1).pdf` — plain-language priority table (feature/complexity/impact) mirroring the phased plan in Implementation Context, plus an "AI Model Decision (Updated)" section that also still names Claude as primary.
- `docs/VIVE_Architecture_After_Planned_Changes (1).pdf` — single-page pipeline diagram marking each stage Unchanged vs. New-to-be-built; consistent with the Implementation Context's phase breakdown; also names Claude as the extraction stage (same staleness as the other two PDFs).

## Open Questions Before Extraction

- **Canonical layer boundary is now confirmed (Silver)** — see header field. Session F extraction should exclude Bronze (raw AI output, not a domain entity layer) and Gold (derived match/exception outcomes, not the entity itself) from entity promotion, per BCE-005's exclusion of "pipeline internals."
- The Scope and Improvement Plan PDFs describe **Claude (Haiku 4.5)** as the primary extraction engine; RULES.md RULE-04 and the Implementation Context Progress Log both state this was superseded twice (→ Azure OpenAI gpt-5-mini → Azure Document Intelligence `prebuilt-layout`), and the Implementation Context's own Section 3 flags itself as not yet revised to match. **This is an existing, self-acknowledged doc-vs-doc divergence, independent of anything Session A finds in code** — Session A must confirm which chain the code actually executes today (expected: Azure Document Intelligence → pdfplumber/OCR) and flag if reality differs from even RULES.md's account.
- Per the standing verification rule for this extraction: RULES.md and VIVE_Implementation_Context.md are themselves docs, not code — every claim above (matching being 2-level not 3-level, the disposition suppression logic being unwired, the active provider chain, RULE-08's flat permission model, etc.) is a Stage-1-equivalent claim to be confirmed or flagged as STAGE-2-DIVERGENCE once Session A reads the actual source.
- Whether `azure_openai_client.py`/gpt-5-mini-nano-5.1 configs and the retired Gemini/Groq removal are fully dead code or still reachable from any live path (e.g. the `--explain` narrative step, which RULES.md says hardcodes Claude directly — itself worth confirming against code).
- Whether the Blob Storage client (`src/storage/blob_client.py`) or job queue exist as any dormant/partial code beyond what Implementation Context describes as "not yet wired."

## Confidence Assessment

HIGH — RULES.md and VIVE_Implementation_Context.md are detailed, actively maintained, engineer-authored living documents with explicit rationale and a dated change history, which is unusually strong pre-code signal. However, per the standing rule for this extraction, HIGH here describes the quality of the docs-derived starting point only — it is not a claim that any statement above has been confirmed against actual runtime code. The self-flagged staleness in the PDFs (Claude vs. the actual current chain) is a concrete demonstration of why that distinction matters.
