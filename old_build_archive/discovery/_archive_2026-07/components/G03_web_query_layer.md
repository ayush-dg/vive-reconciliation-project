## G03 — web query layer
ID: M-011
Layer: infra
Source file: web/queries.py
Rewritten: 2026-07-25 scoped BCE refresh (grew from ~807 to ~1,167 lines across 4 commits, 2026-07-24)

**Module** — web query layer
**ID** — M-011
**Layer** — infra
**Primary Responsibility** — All Azure SQL/SQLite access for the web app (~1,167 lines, up from ~807) — every serving-layer router calls into this module rather than writing SQL directly. Grew four new areas since the last extraction: job-claiming's guard scope narrowed, exception aging/escalation, match-confidence-gated bulk approve, and batch grouping/summarization.

**Inputs** — Function parameters only (statement_id, vendor_name, source_file, email, job_id, batch_id, exception_id, threshold, etc.) — no direct HTTP/request access. New: `create_job()` now accepts an optional `batch_id`.

**Outputs** — Reads return lists/dicts of rows; writes (`create_job`, `update_job_status`, `resolve_exception`, `escalate_exception` [new], `bulk_approve_exceptions` [new], `create_user`, `delete_user_by_email`, `action_review_item`) mutate `jobs`, `exception_dispositions`, `gold_exceptions`, `users`, `validation_document_review_queue` respectively.

**Public Interface** (grouped by area; new functions/areas marked)
- Dashboard: `get_kpis()`, `get_recent_runs(limit=10)`, `get_open_exceptions_count()`, `_live_open_exception_count(statement_id)` (private), `_with_live_exception_counts(rows)` (private) — unchanged
- Exceptions: `get_vendor_summaries()`, `_get_exceptions_only_vendors()` (private), `_vendor_name_from_source_file(source_file)` (private), `get_vendor_latest_statement(vendor_name)`, `get_exceptions_only_vendor(vendor_name)`, `get_open_exceptions(statement_id, reason_filter=None)`, `get_exception_counts(statement_id)`, `get_open_exceptions_for_source_file(source_file, reason_filter=None)`, `get_exception_counts_for_source_file(source_file)`, `resolve_exception(...)` — unchanged
- **Exceptions — aging/escalation/bulk-approve (new, 2026-07-24):** `_parse_datetime(value)` (private — handles Azure SQL's `DATETIME2` columns, e.g. `escalated_at`, coming back as native `datetime` objects while every other timestamp column is a plain ISO string on both backends), `_days_since(iso_timestamp)` (private), `_with_aging_fields(rows)` (private — attaches `days_open`/`days_since_escalated` to every exception row), `escalate_exception(exception_id, escalated_by)`, `get_exception_aging_summary(vendor_name)`, `get_high_confidence_exception_count(vendor_name, threshold=0.99)`, `bulk_approve_exceptions(vendor_name, threshold, reviewed_by)`
- Users: `get_user_by_email(email)`, `list_users()`, `create_user(name, email, password_hash, created_by)`, `delete_user_by_email(email)` — unchanged
- Jobs: `create_job(job_id, pdf_filename, pdf_path, submitted_by, batch_id=None)` (**signature changed** — added `batch_id`), `claim_next_pending_job()` (**guard scope changed**, see Known Fragility), `update_job_status(job_id, status, ...)`, `get_active_jobs()`, `get_job_history()`
- **Batches (new, 2026-07-24):** `_format_duration(total_seconds)` (private), `_stats_for_statement(statement_id)` (private), `_batch_status(batch)` (private), `_batch_time_taken(batch)` (private), `_job_time_taken(job)` (private), `get_all_batches()`, `get_batch_detail(batch_id)`, `get_manual_uploads()`, `get_recent_completed_batches(limit=3)`
- Reports: `get_all_runs()`, `get_statement_report(statement_id)` — unchanged
- Review queue: `_parse_review_row(row)` (private), `get_pending_review_count()`, `get_review_queue_vendors()`, `get_review_queue_for_vendor(source_file)`, `get_review_queue_item(review_id)`, `action_review_item(review_id, action, reviewed_by)` (**now writes `match_confidence` and `shop_owner` on the flagged `gold_exceptions` row it inserts — did not before**)
- `get_vendor_name_for_statement(statement_id)` — unchanged

**Error Behaviour** — No try/except anywhere in this module — every function lets a DB exception propagate to its caller (the router), which in turn has no explicit handling either, so a DB failure anywhere in this module surfaces as an unhandled FastAPI 500. `_parse_review_row()` remains the sole exception (tolerates malformed `raw_payload` JSON). Unchanged from before.

**Known Fragility**
- **`claim_next_pending_job()`'s atomic-claim guard was narrowed on 2026-07-24 from system-wide to per-`pdf_filename` scope** — an engineer-approved amendment (see `discovery/INVARIANT_CATALOGUE.md`'s rewritten IC-19, `docs/Claude.md` v1.1, `docs/INVARIANTS.md`'s amended INV-05) made specifically to let the new worker pool (M-013) actually run different statements concurrently. Still one atomic `UPDATE ... WHERE id = (SELECT MIN(p.id) ...)` — the single-statement design avoiding a SELECT-then-UPDATE race between pool threads is unchanged and still correct by inspection.
- **`resolve_exception()` is not atomic across its two statements** — unchanged from before.
- **`get_recent_runs()`'s SQL-injected `LIMIT {limit}`** — unchanged from before, still guarded by `int()` casting first.
- **`_get_exceptions_only_vendors()`/`get_exceptions_only_vendor()`'s vendor-identity matching is fragile-by-design** — unchanged from before.
- **New: `get_high_confidence_exception_count()`'s default `threshold=0.99` is deliberately unreachable at today's scoring scale** — the module's own docstring states the highest exception `match_confidence` currently produced is `0.90` (Invoice Missing, per `src/matching/engine.py`'s `EXCEPTION_MATCH_CONFIDENCE`), so the "Bulk approve" button this count gates will not surface for any real exception yet at the shipped default. Confirmed deliberate (the docstring calls this "the safest possible default, not tuned to today's scoring scale"), not a bug — but worth flagging that this feature is effectively dormant-by-default until either the threshold is lowered or the scoring scale changes.
- **New: `_days_since()`/`_parse_datetime()`'s dual-format handling is a real, non-optional cross-backend difference, not defensive overengineering** — Azure SQL's `pyodbc` driver returns `DATETIME2` columns (specifically `gold_exceptions.escalated_at`) as native Python `datetime` objects, while every other timestamp column in this schema is `NVARCHAR`/`TEXT` on both backends and always comes back as a plain ISO string. A future new `DATETIME2`-typed column would need the same dual handling or would break on Azure SQL only, not SQLite — an easy-to-miss backend divergence for whoever adds the next timestamp column.
- **New: `get_all_batches()`/`get_batch_detail()` each re-run a per-`statement_id` query loop (`_stats_for_statement()`)** to compute aggregated invoice/exception counts — an N+1-style pattern, acceptable at current batch sizes but a real scaling consideration if a single Event Grid delivery batch grows large (see B09's Known Fragility for the same concern from the router side).
- **New coupling: this module now calls into M-036 (`score_exception_confidence`) and M-048 (`get_shop_owner`) directly** — previously M-011's only outbound dependency was M-033 (the DB layer). `action_review_item()` is the specific call site. This is a genuine new architectural coupling (an infra module now depends on a pipeline module's scoring table and a second infra module's config lookup), not a doc-staleness correction — see `discovery/MODULE_CONTRACTS.md` cross-cutting finding #10.

**Change Impact** — Still the single highest-fan-in module in the `web/` layer — every router depends on it, now including the two new routers (M-045, M-046). Any signature change ripples to whichever router calls that function; any schema change to `gold_exceptions`, `jobs`, `users`, or `validation_document_review_queue` requires a corresponding change here. New: `jobs.batch_id` (migration 007) must be threaded through consistently by every job-creation call site — `create_job()`'s `batch_id` parameter defaults to `None`, so an existing caller that doesn't pass it (there are none currently outside M-007/M-046) would silently produce a `NULL`-batch (manual-upload-shaped) job rather than erroring.

**Callers** — M-001 through M-008 (every original serving-layer router), M-010 (`sidebar_context`), M-013 (worker pool's job-claim loop), **M-045 and M-046 (new, 2026-07-24)**
**Calls** — M-033 (`execute_sql`, `execute_query`), **M-036 (`score_exception_confidence`, new) and M-048 (`get_shop_owner`, new)**
**Integration Points Used** — IP-008 (Lakehouse database)
