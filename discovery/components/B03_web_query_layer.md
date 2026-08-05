## B03 — Web Query Layer
ID: M-003
Layer: serving
Source file: `web/queries.py`

**Module** — Web Query Layer
**ID** — M-003
**Layer** — serving
**Primary Responsibility** — Owns every SQL statement the web app issues; routers never write SQL directly.

**Inputs** — Function parameters only (vendor names, statement IDs, thresholds, form-supplied strings); no direct request/session access.

**Outputs** — Reads/writes across `gold_reconciliation_summary`, `gold_matched_invoices`, `gold_exceptions`, `silver_reconciliation_standard`, `exception_dispositions`, `jobs`, `users`, and — via the Fabric path — `document_intake_log` and `validation_document_review_queue`.

**Public Interface** (grouped by area; ~35 functions total)
- Dashboard: `get_kpis()`, `get_recent_runs()`, `get_open_exceptions_count()`, `get_pending_review_count()`
- Exceptions: `get_vendor_summaries()`, `get_vendor_latest_statement()`, `get_exceptions_only_vendor()`, `get_open_exceptions()`, `get_exception_counts()`, `get_open_exceptions_for_source_file()`, `get_exception_counts_for_source_file()`, `resolve_exception()`, `escalate_exception()`, `get_exception_aging_summary()`, `get_high_confidence_exception_count()`, `bulk_approve_exceptions()`
- Users: `get_user_by_email()`, `list_users()`, `create_user()`, `delete_user_by_email()`
- Jobs: `create_job()`, `claim_next_pending_job()`, `update_job_status()`, `get_active_jobs()`, `get_job_history()`
- Batches: `get_all_batches()`, `get_batch_detail()`, `get_manual_uploads()`, `get_recent_completed_batches()`
- Reports: `get_all_runs()`, `get_statement_report()`, `get_vendor_name_for_statement()`
- Review queue: `get_review_queue_vendors()`, `get_review_queue_for_vendor()`, `get_review_queue_item()`, `action_review_item()`

**Error Behaviour** — No function catches its own DB errors; a query failure propagates as a raw exception to the calling router, which has no explicit handler — FastAPI's default 500 applies. `claim_next_pending_job()` is the one function whose correctness depends entirely on atomicity, not error handling — see Known Fragility.

**Known Fragility**
- `claim_next_pending_job()`'s single-statement atomic claim (`UPDATE ... WHERE id = (SELECT MIN...) AND status = 'PENDING'`) is the entire correctness guarantee for the worker pool (M-005) never double-claiming a job — any refactor toward a SELECT-then-UPDATE pattern would silently reintroduce a race under concurrent workers.
- `_recompute_summary_counts()` is the sole thing keeping `gold_reconciliation_summary.exception_count`/`overall_status` truthful after `resolve_exception()`/`action_review_item()` — any new code path that writes to `gold_exceptions.exception_status` without also calling this (or going through `resolve_exception()`) reintroduces the staleness bug fixed in `3cc3c37`.
- Four functions (`get_pending_review_count`, `get_review_queue_vendors`, `get_review_queue_for_vendor`, `get_review_queue_item`, `action_review_item`'s UPDATE) read/write `validation_document_review_queue` via the Fabric path (`execute_query_fabric`/`execute_sql_fabric`), while everything else in this file stays on the Azure SQL path — a maintainer adding a new query against that table who copies a nearby `execute_query()` call instead of `execute_query_fabric()` would silently target the wrong backend.
- `get_vendor_name_for_statement()` and `get_statement_report()` read `document_intake_log` via Fabric but fall back to `gold_reconciliation_summary` (Azure SQL) on a miss — two different backends contributing to one logical answer.

**Change Impact** — This module is called by every router (M-006–M-015) and is the sole path to three storage backends (SQLite/Azure SQL directly, and Fabric via M-037's fabric functions) — a bug here has the widest blast radius of any serving-layer module.

**Callers** — M-002, M-005, M-006, M-007, M-008, M-009, M-010, M-011, M-012, M-013, M-014, M-015
**Calls** — M-037 (`execute_query`/`execute_sql`/`execute_query_fabric`/`execute_sql_fabric`), M-034 (`score_exception_confidence`, `score_overall_status`), M-042 (`get_shop_owner`)
**Integration Points Used** — IP-008 (Azure SQL/SQLite, transitively via M-037), IP-011 (Fabric Warehouse, transitively via M-037)
