## B09 — batches router
ID: M-045
Layer: serving
Source file: web/routers/batches.py
Added: 2026-07-25 scoped BCE refresh (module built 2026-07-24, Step 11)

**Module** — batches router
**ID** — M-045
**Layer** — serving
**Primary Responsibility** — Batch summary UI for Event Grid auto-intake deliveries: a list view grouping jobs by `batch_id` (plus manually-uploaded jobs, which have `batch_id = NULL`), and a per-batch detail view of every file in that delivery.

**Inputs**
- `GET /batches` — no inputs beyond an authenticated session (`Depends(require_login)`).
- `GET /batches/{batch_id}` — path param `batch_id`.

**Outputs**
- `/batches`: renders `batches.html` with `batches` (from `queries.get_all_batches()`) and `manual_upload_groups` (from `queries.get_manual_uploads()`, grouped by submission date).
- `/batches/{batch_id}`: renders `batch_detail.html` with `batch` (aggregated summary) and `jobs` (per-file rows, each enriched with `invoice_count`/`exception_count`/`time_taken`) from `queries.get_batch_detail(batch_id)`. Redirects to `/batches` (303) if `batch_id` doesn't exist (`data["batch"]` is `None`).
- No database writes — this router is read-only; `batch_id` values themselves are written by M-046 (`create_job()`, one shared UUID per Event Grid delivery) and left `NULL` by M-007 (manual `/upload`).

**Public Interface**
- `batches_list(request, user) -> TemplateResponse` — `GET /batches`
- `batch_detail(batch_id, request, user) -> TemplateResponse | RedirectResponse` — `GET /batches/{batch_id}`

**Error Behaviour** — No explicit try/except in this router; any exception from `queries.get_all_batches()`/`get_manual_uploads()`/`get_batch_detail()` propagates as an unhandled FastAPI 500. The one guarded case is a nonexistent `batch_id`, handled by redirect rather than a 404 or exception.

**Known Fragility**
- **Every batch/job stat is recomputed by `queries.py` on each page load** (`get_all_batches()` re-derives `total_invoices`/`total_exceptions` per batch via a per-`statement_id` query loop, `_stats_for_statement()`) — no caching, no materialized batch-summary table. Fine at current volume; would not scale gracefully to a very large batch history without pagination, which does not exist on `/batches`.
- **A batch's displayed status (`PROCESSING`/`PARTIAL`/`COMPLETED`, via `queries._batch_status()`) is derived purely from job-row counts at read time** — there is no persisted batch-level status column, so this view can never disagree with the underlying `jobs` rows, but also cannot be corrected independently of them (e.g. no manual "mark batch reviewed" state exists).

**Change Impact** — Depends entirely on `web/queries.py`'s three batch functions (`get_all_batches`, `get_manual_uploads`, `get_batch_detail`) and, transitively, on `jobs.batch_id` (migration `007_add_batch_id_to_jobs.sql`) being populated correctly by M-046 and left `NULL` by M-007 — a future job-creation path that forgets to pass (or omit) `batch_id` would silently miscategorize into the wrong section of this UI rather than erroring.

**Callers** — none (top-level HTTP entry point)
**Calls** — M-010 (`render`, `require_login`, `sidebar_context`), M-011 (`get_all_batches`, `get_manual_uploads`, `get_batch_detail`)
**Integration Points Used** — none directly
