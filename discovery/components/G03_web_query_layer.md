## G03 — web query layer
ID: M-011
Layer: infra
Source file: web/queries.py

**Module** — web query layer
**ID** — M-011
**Layer** — infra
**Primary Responsibility** — All Azure SQL/SQLite access for the web app (807 lines) — every serving-layer router calls into this module rather than writing SQL directly.

**Inputs** — Function parameters only (statement_id, vendor_name, source_file, email, job_id, etc.) — no direct HTTP/request access.

**Outputs** — Reads return lists/dicts of rows; writes (`create_job`, `update_job_status`, `resolve_exception`, `create_user`, `delete_user_by_email`, `action_review_item`) mutate `jobs`, `exception_dispositions`, `gold_exceptions`, `users`, `validation_document_review_queue` respectively.

**Public Interface** (33 functions total; grouped by area)
- Dashboard: `get_kpis()`, `get_recent_runs(limit=10)`, `get_open_exceptions_count()`, `_live_open_exception_count(statement_id)` (private), `_with_live_exception_counts(rows)` (private)
- Exceptions: `get_vendor_summaries()`, `_get_exceptions_only_vendors()` (private), `_vendor_name_from_source_file(source_file)` (private), `get_vendor_latest_statement(vendor_name)`, `get_exceptions_only_vendor(vendor_name)`, `get_open_exceptions(statement_id, reason_filter=None)`, `get_exception_counts(statement_id)`, `get_open_exceptions_for_source_file(source_file, reason_filter=None)`, `get_exception_counts_for_source_file(source_file)`, `resolve_exception(exception_id, statement_id, vendor_name, invoice_number, reason_code, disposition_status, notes, disposed_by)`
- Users: `get_user_by_email(email)`, `list_users()`, `create_user(name, email, password_hash, created_by)`, `delete_user_by_email(email)`
- Jobs: `create_job(job_id, pdf_filename, pdf_path, submitted_by)`, `claim_next_pending_job()`, `update_job_status(job_id, status, ...)`, `get_active_jobs()`, `get_job_history()`
- Reports: `get_all_runs()`, `get_statement_report(statement_id)`
- Review queue: `_parse_review_row(row)` (private), `get_pending_review_count()`, `get_review_queue_vendors()`, `get_review_queue_for_vendor(source_file)`, `get_review_queue_item(review_id)`, `action_review_item(review_id, action, reviewed_by)`
- `get_vendor_name_for_statement(statement_id)`

**Error Behaviour** — No try/except anywhere in this module — every function lets a DB exception propagate to its caller (the router), which in turn has no explicit handling either (see B01-B08 contracts), so a DB failure anywhere in this module surfaces as an unhandled FastAPI 500. `_parse_review_row()` is the sole exception: tolerates malformed `raw_payload` JSON (`except (TypeError, ValueError): payload = {}`) rather than raising.

**Known Fragility**
- **`resolve_exception()` is not atomic across its two statements** (INSERT into `exception_dispositions`, then UPDATE `gold_exceptions`) — no explicit transaction wraps them; `execute_sql()` (M-033) commits each statement independently. A crash or connection drop between the two would leave a disposition recorded but the exception still marked OPEN, or vice versa if reordered. Low practical likelihood but a real gap for a system whose whole value proposition is accurate reconciliation state.
- **`claim_next_pending_job()`'s atomic claim** (single UPDATE with a `NOT EXISTS` guard) is a well-reasoned, deliberately single-statement design (per its own extensive docstring) specifically to avoid a race between multiple worker processes — confirmed correct by inspection, not just trusted from the comment.
- **`get_recent_runs()`'s SQL-injected `LIMIT {limit}`** is explicitly *not* a parameterized value — the code comment explains this is because the SQLite→Azure SQL translator (M-033) only rewrites a trailing literal `LIMIT <digit>`, not a bound placeholder. `limit` is cast to `int()` first, which prevents SQL injection (a non-numeric string raises `ValueError` before reaching the query) — confirmed safe by tracing the actual guard, not assumed safe from the comment alone.
- **`_get_exceptions_only_vendors()`/`get_exceptions_only_vendor()`'s vendor-identity matching is fragile-by-design** (own docstring acknowledges "no reliable way to link the two without a real vendor identity on gold_exceptions") — a vendor with both a normal summary-backed card and an orphaned-exception card can appear as two separate entries on the exceptions page.

**Change Impact** — This is the single highest-fan-in module in the `web/` layer — every router depends on it. Any signature change ripples to whichever router calls that function; any schema change to `gold_exceptions`, `jobs`, `users`, or `validation_document_review_queue` requires a corresponding change here.

**Callers** — M-001 through M-008 (every serving-layer router), M-010 (`sidebar_context`), M-013 (worker's job-claim loop)
**Calls** — M-033 (`execute_sql`, `execute_query`)
**Integration Points Used** — IP-008 (Lakehouse database)
