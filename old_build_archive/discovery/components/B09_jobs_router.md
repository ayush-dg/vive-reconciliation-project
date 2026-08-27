## B09 — Jobs Router
ID: M-009
Layer: serving
Source file: `web/routers/jobs.py`

**Module** — Jobs Router
**ID** — M-009
**Layer** — serving
**Primary Responsibility** — JSON job-queue status endpoint (polled by dashboard auto-refresh JS) and a full job history page.

**Inputs** — None beyond the login session.

**Outputs** — `GET /jobs` returns a JSON list (fixed field subset via `_JOB_FIELDS`); `GET /jobs/history` renders `jobs_history.html`.

**Public Interface** — `GET /jobs`, `GET /jobs/history` — no functions called by other modules.

**Error Behaviour** — None explicit; relies on default FastAPI error handling.

**Known Fragility** — `_job_json()`'s field whitelist (`_JOB_FIELDS`) must be kept in sync by hand with whatever `web/static/app.js` actually reads — no shared contract/type enforces this; a field renamed in `jobs` table or added to the frontend's expectations without updating both sides fails silently (missing key, not an error).

**Change Impact** — Isolated; the only consumer of `/jobs`'s JSON shape is `web/static/app.js`, not read this session.

**Callers** — M-001 (router registration)
**Calls** — M-002 (`render`, `require_login`, `sidebar_context`), M-003 (`get_active_jobs`, `get_job_history`)
**Integration Points Used** — none
