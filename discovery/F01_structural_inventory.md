STAGE-F1-DRAFT: STRUCTURAL

# F01 — Structural Extraction — VIVE Reconciliation
Produced by: BCE Session F01 (CC)
Date: 2026-08-05

**Canonical layer boundary:** `silver_reconciliation_standard` (declared in `discovery/INTAKE_SUMMARY.md`).

**Sources read, in priority order:** (1) Migration scripts — `migrations/001_initial_schema.sql` through `009_add_routing_aging.sql`, complete structural history in creation order, read in full this session. (2) Schema dump / DDL — `src/lakehouse/azure_sql_migrations.py`'s `TABLES`/`COLUMNS`/`COMPUTED_COLUMNS` dicts (T-SQL mirror of the same schema, current state), read in full this session. No ORM model definitions, GraphQL schema, OpenAPI/JSON Schema, or existing ERD/data dictionary exist in this codebase. `notebooks/00_setup_lakehouse_schema.py`'s bootstrap of `schema_version` (via `src/lakehouse/migrations.py`) is the 15th table, created by the migration runner itself rather than a numbered migration file.

Per BCE-F01 instruction, **every candidate table is recorded below — promotion/exclusion happens at F03**, scoped to the canonical layer boundary.

---

## Entity Inventory

| Entity/Table Name | Columns | Types | Notes |
|---|---|---|---|
| `bronze_vendor_statement_raw` | id, vendor_id, vendor_name, source_file, statement_id, statement_period, page_number, row_number, ingestion_timestamp, raw_invoice_number, raw_invoice_date, raw_due_date, raw_amount, raw_outstanding_amount, raw_ro_number, raw_po_number, raw_work_order_number, raw_description, raw_credit, raw_shop_name, raw_currency, extraction_confidence, extraction_model, raw_ai_response | id INTEGER PK; all `raw_*` fields TEXT (untyped by design — Bronze is append-only raw extraction, see `INTAKE_SUMMARY.md`); extraction_confidence REAL | Bronze layer — pipeline internal, outside canonical boundary. One row per extracted invoice line, one attempt. |
| `bronze_internal_erp_raw` | id, vendor_id, source, statement_id, statement_period, ingestion_timestamp, raw_invoice_number, raw_invoice_date, raw_posting_date, raw_amount, raw_outstanding_amount, raw_ro_number, raw_po_number, raw_shop, raw_status, erp_version | id INTEGER PK; source TEXT DEFAULT 'MOCK_ERP'; raw_status TEXT DEFAULT 'POSTED'; erp_version INTEGER DEFAULT 1 | Bronze layer (mock-ERP side) — pipeline internal, outside canonical boundary. |
| **`silver_reconciliation_standard`** | id, record_id, record_source, document_type, statement_id, statement_date, vendor_id, vendor_name, shop, invoice_number, invoice_number_normalized, invoice_date, ro_number, po_number, work_order_number, amount, credit, outstanding_amount, due_date, posting_date, status, description, currency, statement_period, source_file, ingestion_timestamp | id INTEGER PK; record_id TEXT UNIQUE NOT NULL; record_source TEXT NOT NULL CHECK IN ('VENDOR_STATEMENT','INTERNAL_ERP'); amount/credit/outstanding_amount REAL; rest TEXT | **Canonical layer.** Shared schema for both vendor-statement and internal-ERP sides, distinguished only by `record_source`. This is the declared entity boundary — see F03. |
| `gold_matched_invoices` | id, match_id, vendor_id, shop, invoice_number, ro_number, statement_amount, erp_amount, match_level, match_status, statement_record_id, erp_record_id, source_file, statement_id, match_timestamp, statement_period, match_confidence | id INTEGER PK; match_id TEXT UNIQUE NOT NULL; match_level INTEGER; match_status TEXT DEFAULT 'MATCHED'; match_confidence REAL (added migration 008) | Gold layer — derived match outcome, outside canonical boundary (not the entity itself). |
| `gold_exceptions` | id, exception_id, vendor_id, shop, invoice_number, ro_number, statement_amount, erp_amount, match_status, exception_reason, exception_status, statement_record_id, source_file, statement_id, date_raised, date_resolved, statement_period, ai_explanation, ai_suggested_resolution, ai_confidence_score, ai_provider, match_confidence, shop_owner, escalation_status, escalated_at, escalated_by | id INTEGER PK; exception_id TEXT UNIQUE NOT NULL; match_status TEXT DEFAULT 'EXCEPTION'; exception_status TEXT DEFAULT 'OPEN'; match_confidence REAL (migration 008); shop_owner/escalation_status/escalated_at/escalated_by TEXT (migration 009, escalation_status DEFAULT 'NONE') | Gold layer — derived exception outcome, outside canonical boundary. **Platform note (not a divergence):** Azure SQL's mirror additionally computes `days_open` as `DATEDIFF(day, date_raised, GETUTCDATE())`, a true generated column; SQLite has no equivalent (generated columns can't reference current time) — the app computes "days open" in Python (`web/queries.py:_days_since()`) on both backends instead. Deliberate, documented in migration 009's own header comment — not an unresolved divergence. |
| `gold_reconciliation_summary` | id, summary_id, vendor_id, vendor_name, shop, statement_period, statement_id, statement_total, erp_total, difference, total_invoice_count, matched_count, exception_count, match_percentage, overall_status, reconciliation_timestamp, erp_version | id INTEGER PK; summary_id TEXT UNIQUE NOT NULL; totals/difference/match_percentage REAL; counts INTEGER | Gold layer — one snapshot row per matching run, outside canonical boundary. Historically prone to a staleness gap (fixed `3cc3c37` — see `TOPOLOGY.md` A01 row 5). |
| `document_intake_log` | id, document_id, document_hash, source_file, ingestion_timestamp, document_type, document_type_confidence, vendor_name, shop_or_entity, statement_date, statement_period, currency, statement_total_as_printed, extraction_confidence_overall, extraction_model, extraction_method, routing_decision, statement_id, invoice_count, warnings, schema_version, blob_storage_path, original_filename, uploaded_by, uploaded_at | id INTEGER PK; document_id TEXT UNIQUE NOT NULL; confidences REAL; invoice_count INTEGER; blob_storage_path/original_filename/uploaded_by/uploaded_at added migration 003 | Metadata/audit table, outside canonical boundary. **Cut over to Fabric Warehouse** (`execute_query_fabric`/`execute_sql_fabric`) — see `TOPOLOGY.md` A01 row 8. |
| `ai_audit_log` | id, audit_id, source_file, vendor_id, statement_id, interaction_type, ai_provider, model, prompt_version, request_timestamp, latency_ms, attempt_count, success, response_status, error_message, extraction_confidence, validation_result | id INTEGER PK; audit_id TEXT UNIQUE NOT NULL; success INTEGER (0/1 boolean); latency_ms/extraction_confidence REAL; attempt_count INTEGER DEFAULT 1 | Platform/audit table, outside canonical boundary. Still Azure SQL, not cut over to Fabric. |
| `validation_document_review_queue` | id, review_id, vendor_id, source_file, statement_id, statement_period, pipeline_stage, rejection_category, rejection_details, extraction_confidence, confidence_threshold_applied, raw_payload, review_status, flagged_timestamp, reviewed_by, reviewed_timestamp, resolution_notes | id INTEGER PK; review_id TEXT UNIQUE NOT NULL; review_status TEXT DEFAULT 'PENDING_REVIEW'; confidences REAL | Platform/queue table, outside canonical boundary. **Cut over to Fabric Warehouse.** |
| `extraction_cache` | id, document_hash, statement_id, source_file, extraction_method, row_count, ingestion_timestamp | id INTEGER PK; UNIQUE(document_hash, statement_id); row_count INTEGER | Platform/cache table, outside canonical boundary. **Cut over to Fabric Warehouse** (the first table migrated). |
| `exception_dispositions` | id, exception_id, statement_id, vendor_name, invoice_number, reason_code, disposition_status, disposition_notes, disposed_by, disposed_at, created_at | id INTEGER PK; disposition_status TEXT NOT NULL CHECK IN ('ACCEPTED','DISPUTED','DUPLICATE','WRITE_OFF','PENDING'); created_at DEFAULT CURRENT_TIMESTAMP | Human-audit table, outside canonical boundary. Lookup key is `(vendor_name, invoice_number, reason_code)`, not `statement_id`, by design — see migration 002's header comment (statement_id changes every period even for a recurring exception). |
| `users` | id, name, email, password_hash, is_active, created_at, created_by | id INTEGER PK; email TEXT UNIQUE NOT NULL; is_active INTEGER (0/1 boolean) DEFAULT 1 | Platform/identity table, outside canonical boundary. |
| `jobs` | id, job_id, pdf_filename, pdf_path, statement_id, status, submitted_by, submitted_at, started_at, completed_at, error_message, vendor_name, claim_token, batch_id | id INTEGER PK; job_id TEXT UNIQUE NOT NULL; status TEXT NOT NULL DEFAULT 'PENDING' CHECK IN ('PENDING','PROCESSING','COMPLETED','FAILED'); claim_token TEXT (migration 006); batch_id TEXT (migration 007) | Platform/queue table, outside canonical boundary. |
| `schema_version` | version, filename, applied_at | version TEXT PK; filename/applied_at TEXT NOT NULL | Bootstrap table, created by `src/lakehouse/migrations.py`'s `_ensure_schema_version_table()`, not a numbered migration file itself. Pure platform bookkeeping, outside canonical boundary. |

---

## Relationship Inventory

**No table in this schema declares an enforced FOREIGN KEY anywhere** — confirmed directly across all 9 migration files. Every cross-table link is a plain-value convention, documented explicitly in migration 002's own header comment ("by convention, not an enforced FOREIGN KEY... which follows the same pattern throughout"). All relationships below are therefore `INFERRED`, not `ORM_RELATION`/`JOIN_TABLE`.

| Relationship | Declaration Type | Source Entity | Target Entity | Notes |
|---|---|---|---|---|
| Bronze row belongs to a Silver row | INFERRED | `bronze_vendor_statement_raw` | `silver_reconciliation_standard` | Linked by shared `statement_id`, not a stored key reference. Normalization (`normalize_to_silver()`) re-derives Silver rows fresh from Bronze on every run. |
| Silver VENDOR_STATEMENT row is matched or excepted | INFERRED | `silver_reconciliation_standard` (record_source=VENDOR_STATEMENT) | `gold_matched_invoices` OR `gold_exceptions` | Linked via `statement_record_id` (stores the Silver `record_id` value). Mutually exclusive by construction — `classify_match()` returns exactly one of MATCHED/EXCEPTION per statement line, never both. |
| Silver INTERNAL_ERP row is consumed by a match | INFERRED | `silver_reconciliation_standard` (record_source=INTERNAL_ERP) | `gold_matched_invoices` | Linked via `erp_record_id`. An ERP row not consumed by any match simply has no corresponding `gold_matched_invoices` row — no orphan-tracking mechanism. |
| Matching run produces one summary | INFERRED | `gold_matched_invoices` + `gold_exceptions` | `gold_reconciliation_summary` | Linked via shared `statement_id`; `run_matching()` writes counts/totals into the summary row in the same call that populates the two detail tables. |
| Exception has a recorded human decision | INFERRED | `gold_exceptions` | `exception_dispositions` | **Different key shape than every other relationship in this schema** — linked via `(vendor_name, invoice_number, reason_code)`, not `exception_id`/`statement_id` (both of which exist as columns on `exception_dispositions` but are not the lookup key), deliberately so a recurring exception is recognized across statement periods. See Naming Pattern Flags below. |
| Job produces a statement | INFERRED | `jobs` | `document_intake_log`, `gold_reconciliation_summary` | Linked via `statement_id`, populated only once the pipeline determines it (stays NULL if the job fails before Step 3 of intake). |
| Document intake log describes a Silver/Gold statement | INFERRED | `document_intake_log` | `silver_reconciliation_standard`, `gold_reconciliation_summary` | Linked via shared `statement_id`. On a cache hit, `write_intake_log()` is NOT called again (confirmed in `notebooks/01_document_intake.py`'s `run_intake()`) — `document_intake_log` can have no row for a `statement_id` that nonetheless has Silver/Gold data. |
| Review queue item may be promoted to an exception | INFERRED | `validation_document_review_queue` | `gold_exceptions` | Only when flagged (not approved) — `action_review_item()` inserts a new `gold_exceptions` row with a fresh `exception_id`, no reference back to `review_id` stored on the exception row. One-directional promotion, not a stored link. |

---

## Constraint Inventory

| Entity | Constraint Type | Fields | Notes |
|---|---|---|---|
| `silver_reconciliation_standard` | UNIQUE | `record_id` | SHA-256 hash of source+invoice+amount — the closest thing to a natural key this table has. |
| `silver_reconciliation_standard` | CHECK | `record_source` | Must be `'VENDOR_STATEMENT'` or `'INTERNAL_ERP'` — the two-sided-schema mechanism itself. |
| `gold_matched_invoices` | UNIQUE | `match_id` | UUID, surrogate only. |
| `gold_exceptions` | UNIQUE | `exception_id` | UUID, surrogate only. |
| `gold_reconciliation_summary` | UNIQUE | `summary_id` | UUID, surrogate only. |
| `document_intake_log` | UNIQUE | `document_id` | UUID, surrogate only. |
| `ai_audit_log` | UNIQUE | `audit_id` | UUID, surrogate only. |
| `validation_document_review_queue` | UNIQUE | `review_id` | UUID, surrogate only. |
| `extraction_cache` | UNIQUE | `(document_hash, statement_id)` | Composite — the actual dedup key (RULE-02). |
| `users` | UNIQUE | `email` | Real natural key — login identity. |
| `jobs` | UNIQUE | `job_id` | UUID, surrogate only. |
| `exception_dispositions` | CHECK | `disposition_status` | Must be one of `ACCEPTED`/`DISPUTED`/`DUPLICATE`/`WRITE_OFF`/`PENDING`. |
| `jobs` | CHECK | `status` | Must be one of `PENDING`/`PROCESSING`/`COMPLETED`/`FAILED`. |
| `bronze_vendor_statement_raw` | NOT_NULL | `source_file`, `statement_id`, `ingestion_timestamp` | |
| `bronze_internal_erp_raw` | NOT_NULL | `statement_id`, `ingestion_timestamp` | |
| `silver_reconciliation_standard` | NOT_NULL | `record_id`, `record_source`, `statement_id` | Note: `invoice_number`/`outstanding_amount` are **not** database-enforced NOT NULL here — that guarantee (INV-04 in `docs/INVARIANTS.md`) is enforced one layer up, in `validate_invoice()` (`notebooks/01_document_intake.py`) before a row is ever written to Bronze, not by a schema constraint on Silver itself. |
| `exception_dispositions` | NOT_NULL | `exception_id`, `statement_id`, `vendor_name`, `invoice_number` | |
| `jobs` | NOT_NULL | `job_id`, `pdf_filename`, `pdf_path`, `submitted_at` | |
| `users` | NOT_NULL | `name`, `email`, `password_hash` | |
| `jobs`, `users` | INDEX | `jobs(status, submitted_at)`; `exception_dispositions(vendor_name, invoice_number, reason_code)` | Both added specifically to support a hot lookup path (job polling; recurring-exception lookup) — confirmed via migration header comments, not guessed. |

---

## Divergence Flags

None. SQLite migrations (source of truth for schema history, per `src/lakehouse/azure_sql_migrations.py`'s own docstring) and the Azure SQL DDL mirror agree on every table, column, and constraint checked this session, with one already-explained, already-documented platform difference (`gold_exceptions.days_open`, noted in the Entity Inventory above) — not raised as an open `STAGE-F1-DIVERGENCE` flag because the migration file itself states the reason and the resolution (computed in Python on both backends) in its own header comment. No unresolved schema-vs-migration disagreement was found.

---

F01 is complete. `discovery/F01_structural_inventory.md` must be committed and reviewed before F02 begins.
