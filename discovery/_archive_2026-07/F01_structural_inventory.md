STAGE-F1-DRAFT: STRUCTURAL — 2026-07-23 — Produced by BCE Session F01 (CC)

Canonical layer boundary: Silver layer (`silver_reconciliation_standard`) — per `discovery/INTAKE_SUMMARY.md`, confirmed by engineer 2026-07-23.

**Pre-condition assessment (re-confirmed):** No maintained metadata catalog in use (Step 1 — no). Data layer exists structurally via numbered SQL migrations (Step 2 — yes) → FULL EXTRACTION.

**Sources read, in priority order:**
1. ORM model definitions — **absent.** No ORM in this codebase; `src/lakehouse/connection.py` is a thin `execute_sql`/`execute_query` wrapper over raw SQL (SQLite via `sqlite3`, Azure SQL via `pyodbc`). Confirmed by direct inspection during Session A, not assumed.
2. Migration scripts — **present and read directly** (not inferred from `azure_sql_migrations.py`'s T-SQL mirror, per the standing verification rule): `migrations/001_initial_schema.sql` through `006_add_job_claim_token.sql`.
3. Schema dump / DDL — **the live local SQLite database** (`lakehouse/reconciliation.db`) was also queried directly (`sqlite_master`, `PRAGMA table_info`, `schema_version`) to check for drift between declared migrations and actual applied schema. See Divergence Flags.
4-6. GraphQL / OpenAPI / ERD — not present; not applicable.

This inventory records every table found across the full lakehouse schema (Bronze/Silver/Gold plus operational tables), since all of it lives in one migration history — no promotion or exclusion decision is made here. Session F03 will bound entity promotion to the Silver layer per the canonical boundary declaration; tables outside it are noted below as pipeline/operational internals for that purpose.

---

## Entity Inventory

| Entity/Table Name | Columns | Types | Notes |
|---|---|---|---|
| `bronze_vendor_statement_raw` | id, vendor_id, vendor_name, source_file, statement_id, statement_period, page_number, row_number, ingestion_timestamp, raw_invoice_number, raw_invoice_date, raw_due_date, raw_amount, raw_outstanding_amount, raw_ro_number, raw_po_number, raw_work_order_number, raw_description, raw_credit, raw_shop_name, raw_currency, extraction_confidence, extraction_model, raw_ai_response | INTEGER PK, TEXT×19, INTEGER×2, REAL | Bronze layer — pipeline internal, outside canonical (Silver) boundary. All `raw_*` fields stored as TEXT even where numeric (amount/outstanding_amount), typed only on normalization into Silver. |
| `bronze_internal_erp_raw` | id, vendor_id, source, statement_id, statement_period, ingestion_timestamp, raw_invoice_number, raw_invoice_date, raw_posting_date, raw_amount, raw_outstanding_amount, raw_ro_number, raw_po_number, raw_shop, raw_status, erp_version | INTEGER PK, TEXT×12, INTEGER | Bronze layer — pipeline internal, outside canonical boundary. Mock-ERP-generated (RULE-06), `source` defaults `'MOCK_ERP'`. |
| `silver_reconciliation_standard` | id, record_id, record_source, document_type, statement_id, statement_date, vendor_id, vendor_name, shop, invoice_number, invoice_number_normalized, invoice_date, ro_number, po_number, work_order_number, amount, credit, outstanding_amount, due_date, posting_date, status, description, currency, statement_period, source_file, ingestion_timestamp | INTEGER PK, TEXT×20, REAL×3 | **Canonical layer.** Single shared schema for both `VENDOR_STATEMENT` and `INTERNAL_ERP` sides, distinguished by `record_source`. This is where "Invoice" exists as a business entity. |
| `gold_matched_invoices` | id, match_id, vendor_id, shop, invoice_number, ro_number, statement_amount, erp_amount, match_level, match_status, statement_record_id, erp_record_id, source_file, statement_id, match_timestamp, statement_period | INTEGER PK, TEXT×11, REAL×2, INTEGER | Gold layer — derived match outcome, outside canonical boundary (a relationship/outcome over Silver invoices, not the entity itself). |
| `gold_exceptions` | id, exception_id, vendor_id, shop, invoice_number, ro_number, statement_amount, erp_amount, match_status, exception_reason, exception_status, statement_record_id, source_file, statement_id, date_raised, date_resolved, statement_period, ai_explanation, ai_suggested_resolution, ai_confidence_score, ai_provider | INTEGER PK, TEXT×17, REAL×3 | Gold layer — derived exception outcome, outside canonical boundary. |
| `gold_reconciliation_summary` | id, summary_id, vendor_id, vendor_name, shop, statement_period, statement_id, statement_total, erp_total, difference, total_invoice_count, matched_count, exception_count, match_percentage, overall_status, reconciliation_timestamp, erp_version | INTEGER PK, TEXT×9, REAL×5, INTEGER×3 | Gold layer — derived per-run aggregate, outside canonical boundary. |
| `document_intake_log` | id, document_id, document_hash, source_file, ingestion_timestamp, document_type, document_type_confidence, vendor_name, shop_or_entity, statement_date, statement_period, currency, statement_total_as_printed, extraction_confidence_overall, extraction_model, extraction_method, routing_decision, statement_id, invoice_count, warnings, schema_version, blob_storage_path, original_filename, uploaded_by, uploaded_at | INTEGER PK, TEXT×20, REAL×3, INTEGER | Operational/audit log, one row per intake run — outside canonical boundary. Last 4 columns added by migration 003. |
| `ai_audit_log` | id, audit_id, source_file, vendor_id, statement_id, interaction_type, ai_provider, model, prompt_version, request_timestamp, latency_ms, attempt_count, success, response_status, error_message, extraction_confidence, validation_result | INTEGER PK, TEXT×12, REAL×2, INTEGER×2 | Operational audit trail — outside canonical boundary. |
| `validation_document_review_queue` | id, review_id, vendor_id, source_file, statement_id, statement_period, pipeline_stage, rejection_category, rejection_details, extraction_confidence, confidence_threshold_applied, raw_payload, review_status, flagged_timestamp, reviewed_by, reviewed_timestamp, resolution_notes | INTEGER PK, TEXT×14, REAL×2 | Operational review queue — outside canonical boundary. |
| `extraction_cache` | id, document_hash, statement_id, source_file, extraction_method, row_count, ingestion_timestamp | INTEGER PK, TEXT×4, INTEGER×2 | Operational cache — outside canonical boundary. |
| `exception_dispositions` | id, exception_id, statement_id, vendor_name, invoice_number, reason_code, disposition_status, disposition_notes, disposed_by, disposed_at, created_at | INTEGER PK, TEXT×10 | Operational disposition record — outside canonical boundary, but a strong candidate for a `Relationship`/lifecycle annotation on the Silver `Invoice`/exception concept at F03. |
| `users` | id, name, email, password_hash, is_active, created_at, created_by | INTEGER PK, TEXT×5, INTEGER | Operational (auth) — outside canonical boundary. **Not present in the local SQLite live schema as of this session** — see Divergence Flags. |
| `jobs` | id, job_id, pdf_filename, pdf_path, statement_id, status, submitted_by, submitted_at, started_at, completed_at, error_message, vendor_name, claim_token | INTEGER PK, TEXT×11, INTEGER | Operational (job queue) — outside canonical boundary. **Not present in the local SQLite live schema as of this session** — see Divergence Flags. `claim_token` added by migration 006. |
| `schema_version` | version, filename, applied_at | TEXT×3 (version is PK) | Migration bookkeeping — not a domain entity candidate. |
| `sqlite_sequence` | (SQLite-internal, AUTOINCREMENT bookkeeping) | — | SQLite-internal system table — not a domain entity candidate. |

---

## Relationship Inventory

No table in this schema uses an enforced `FOREIGN KEY` constraint anywhere — confirmed by direct read of all six migration files. Migration 002's own comment states this explicitly as a deliberate, consistent pattern ("by convention, not an enforced FOREIGN KEY... follows the same pattern throughout"), despite `src/lakehouse/connection.py` setting `PRAGMA foreign_keys=ON` for every SQLite connection — that pragma currently has nothing to enforce. Every relationship below is `INFERRED` from shared key values, not a declared schema constraint.

| Relationship | Declaration Type | Source Entity | Target Entity | Notes |
|---|---|---|---|---|
| Vendor-statement rows normalize into Silver | INFERRED | `bronze_vendor_statement_raw` | `silver_reconciliation_standard` | Joined on `statement_id`; `record_source = 'VENDOR_STATEMENT'` |
| ERP rows normalize into Silver | INFERRED | `bronze_internal_erp_raw` | `silver_reconciliation_standard` | Joined on `statement_id`; `record_source = 'INTERNAL_ERP'` |
| Silver statement-side row is matched or excepted | INFERRED | `silver_reconciliation_standard` | `gold_matched_invoices` | Via `gold_matched_invoices.statement_record_id = silver.record_id` |
| Silver ERP-side row is matched | INFERRED | `silver_reconciliation_standard` | `gold_matched_invoices` | Via `gold_matched_invoices.erp_record_id = silver.record_id` |
| Silver statement-side row raises an exception | INFERRED | `silver_reconciliation_standard` | `gold_exceptions` | Via `gold_exceptions.statement_record_id = silver.record_id` |
| Exception is disposed by an AP reviewer | INFERRED | `gold_exceptions` | `exception_dispositions` | **Not by ID at all** — composite natural key `(vendor_name, invoice_number, reason_code)`, deliberately not `statement_id`-keyed so a recurring exception is recognized across statement periods (migration 002 comment). |
| Intake run produces Bronze + Silver rows for a statement | INFERRED | `document_intake_log` | `bronze_vendor_statement_raw` / `silver_reconciliation_standard` | Joined on `statement_id`, one `document_intake_log` row per statement (existing row deleted and replaced on reprocess). |
| Job produces an intake run | INFERRED | `jobs` | `document_intake_log` | `jobs.statement_id` is populated only once the subprocess pipeline determines it (`web/worker.py`) — null until COMPLETED. |
| User submits a job | INFERRED | `users` | `jobs` | By value match on `jobs.submitted_by = users.email`, not a stored ID reference. |
| User disposes an exception | INFERRED | `users` | `exception_dispositions` | By value match on `disposed_by = users.email`. |
| User creates another user | INFERRED | `users` | `users` | Self-referential, by value match on `created_by = users.email`; `NULL` for the seed/fallback account. |
| Reconciliation run aggregates matches/exceptions | INFERRED | `gold_matched_invoices` / `gold_exceptions` | `gold_reconciliation_summary` | Joined on `statement_id`; summary computed and written once per matching run, not maintained incrementally. |

---

## Constraint Inventory

| Entity | Constraint Type | Fields | Notes |
|---|---|---|---|
| `silver_reconciliation_standard` | UNIQUE | `record_id` | |
| `silver_reconciliation_standard` | CHECK | `record_source` | `IN ('VENDOR_STATEMENT', 'INTERNAL_ERP')` |
| `silver_reconciliation_standard` | NOT_NULL | `record_id`, `record_source`, `statement_id` | |
| `gold_matched_invoices` | UNIQUE | `match_id` | |
| `gold_exceptions` | UNIQUE | `exception_id` | |
| `gold_reconciliation_summary` | UNIQUE | `summary_id` | |
| `document_intake_log` | UNIQUE | `document_id` | |
| `document_intake_log` | NOT_NULL | `document_id`, `source_file`, `ingestion_timestamp` | |
| `ai_audit_log` | UNIQUE | `audit_id` | |
| `ai_audit_log` | NOT_NULL | `audit_id`, `interaction_type`, `request_timestamp`, `success` | |
| `validation_document_review_queue` | UNIQUE | `review_id` | |
| `validation_document_review_queue` | NOT_NULL | `review_id`, `flagged_timestamp` | |
| `extraction_cache` | UNIQUE | `(document_hash, statement_id)` composite | |
| `extraction_cache` | NOT_NULL | `document_hash`, `statement_id` | |
| `exception_dispositions` | CHECK | `disposition_status` | `IN ('ACCEPTED', 'DISPUTED', 'DUPLICATE', 'WRITE_OFF', 'PENDING')` |
| `exception_dispositions` | NOT_NULL | `exception_id`, `statement_id`, `vendor_name`, `invoice_number`, `disposition_status`, `created_at` | |
| `exception_dispositions` | INDEX | `(vendor_name, invoice_number, reason_code)` | `idx_exception_dispositions_lookup` — supports cross-statement recurrence lookup |
| `users` | UNIQUE | `email` | |
| `users` | NOT_NULL | `name`, `email`, `password_hash`, `is_active`, `created_at` | |
| `jobs` | UNIQUE | `job_id` | |
| `jobs` | CHECK | `status` | `IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')` |
| `jobs` | NOT_NULL | `job_id`, `pdf_filename`, `pdf_path`, `status`, `submitted_at` | |
| `jobs` | INDEX | `(status, submitted_at)` | `idx_jobs_status_submitted` — supports the worker's oldest-PENDING poll |

---

## Divergence Flags

| Flag ID | Source A | Source B | What Diverges | Notes |
|---|---|---|---|---|
| STAGE-F1-DIVERGENCE-001 | Migration files (`migrations/004_add_users_table.sql`, `005_add_jobs_table.sql`, `006_add_job_claim_token.sql`) declare `users` and `jobs` tables | Live local SQLite schema (`lakehouse/reconciliation.db`) — confirmed via `schema_version` (only 001-003 recorded as applied) and `sqlite_master` (no `users`/`jobs` tables present) | Local dev database was missing 3 applied migrations that exist as files. Azure SQL (checked separately during Session A/E follow-up) already had both tables with data (2 users, 10 jobs rows). | **RESOLVED — 2026-07-23.** `notebooks/00_setup_lakehouse_schema.py` was run locally (engineer-requested); migrations 004-006 applied cleanly with no errors. `schema_version` now records 001-006. Column-level verification (`PRAGMA table_info`) confirms `users` (7 columns) and `jobs` (13 columns, including `claim_token` from 006) match their migration files exactly; both tables created empty (0 rows) as expected. This was never a schema-authoring conflict — confirmed, not just inferred, to be a local database simply not yet re-migrated. No RISK_REGISTER action needed. |

No other divergence found — column-level spot check (`document_intake_log`, `silver_reconciliation_standard`, `exception_dispositions`) against live `PRAGMA table_info` confirms exact match with migrations 001-003 for every column, type, and default.

---

F01 is complete. `discovery/F01_structural_inventory.md` must be committed and reviewed before F02 begins.
