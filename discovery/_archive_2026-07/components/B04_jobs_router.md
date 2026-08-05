## B04 — jobs router
ID: M-004
Layer: serving
Source file: web/routers/jobs.py

**Module** — jobs router
**ID** — M-004
**Layer** — serving
**Primary Responsibility** — Job-queue status as JSON (polled by the dashboard for auto-refresh) and a full job-history page.

**Inputs** — `GET /jobs` — no inputs. `GET /jobs/history` — no inputs.

**Outputs** — `/jobs` returns a JSON array (not a template) of active jobs, each field-filtered to `_JOB_FIELDS` (job_id, pdf_filename, status, submitted_by, submitted_at, started_at, completed_at, error_message, statement_id, vendor_name). `/jobs/history` renders `jobs_history.html` with every job ever submitted. No writes.

**Public Interface**
- `jobs_status(request, user) -> list[dict]` — `GET /jobs`, consumed by `web/static/app.js`'s polling loop
- `jobs_history(request, user) -> TemplateResponse` — `GET /jobs/history`

**Error Behaviour** — No explicit handling; any `queries` exception propagates as an unhandled 500, which would surface to the polling JS as a failed fetch (client-side handling not traced here — out of scope for this contract, see `web/static/app.js`).

**Known Fragility** — `_job_json()`'s field allowlist (`_JOB_FIELDS`) means any new column added to `jobs` (e.g. a future `claim_token` exposure) is silently excluded from the JSON response unless this tuple is updated — a safe-by-default design (no accidental leakage of new columns), but worth noting for future schema changes.

**Change Impact** — Depends on `jobs` table existing (see F01 divergence, now resolved locally) and on `queries.get_active_jobs()`/`get_job_history()`'s exact column names matching `_JOB_FIELDS`.

**Callers** — none (top-level HTTP entry point; polled by client-side JS, not by another Python module)
**Calls** — M-010 (`render`, `require_login`, `sidebar_context`), M-011 (`get_active_jobs`, `get_job_history`)
**Integration Points Used** — none directly
