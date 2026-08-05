## B07 — Dashboard Router
ID: M-007
Layer: serving
Source file: `web/routers/dashboard.py`

**Module** — Dashboard Router
**ID** — M-007
**Layer** — serving
**Primary Responsibility** — Renders the home page: KPI totals, recent runs, active jobs, recent completed batches.

**Inputs** — `require_login` session dependency only; no query params.

**Outputs** — Rendered `home.html` with `kpis`, `runs`, `active_jobs`, `recent_batches`, and two date-label strings.

**Public Interface** — `GET /` — not called by other modules.

**Error Behaviour** — No explicit error handling; any query failure in M-003 propagates to a default 500.

**Known Fragility** — Calls four separate M-003 functions sequentially on every home-page load (`get_kpis`, `get_recent_runs`, `get_active_jobs`, `get_recent_completed_batches`), each issuing its own DB round-trip(s) — `get_kpis()` alone issues 2 queries, `get_recent_completed_batches()` calls `get_all_batches()` which issues 1 + N queries (N = number of distinct batches' statement lookups). No caching; home page cost scales with total batch/job history.

**Change Impact** — Isolated to the home page; a change here does not affect other routers.

**Callers** — M-001 (router registration)
**Calls** — M-002 (`render`, `require_login`, `sidebar_context`), M-003 (`get_kpis`, `get_recent_runs`, `get_active_jobs`, `get_recent_completed_batches`)
**Integration Points Used** — none
