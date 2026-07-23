## B02 — dashboard router
ID: M-002
Layer: serving
Source file: web/routers/dashboard.py

**Module** — dashboard router
**ID** — M-002
**Layer** — serving
**Primary Responsibility** — Home page: KPI totals and a table of recent reconciliation runs.

**Inputs** — `GET /` — no inputs beyond an authenticated session (enforced via `Depends(require_login)`).

**Outputs** — Renders `home.html` with `kpis` (from `queries.get_kpis()`), `runs` (10 most recent, from `queries.get_recent_runs(limit=10)`), `active_jobs` (from `queries.get_active_jobs()`), plus a formatted dashboard title/month label. No database writes.

**Public Interface**
- `home(request: Request, user: str = Depends(require_login)) -> TemplateResponse` — `GET /`

**Error Behaviour** — No explicit error handling in this module; any exception from the three `queries` calls propagates as an unhandled FastAPI 500. `require_login` raises `LoginRequired`, caught globally by `web/app.py`'s exception handler (redirects to `/login`), not handled here.

**Known Fragility** — This route calls three separate query functions (`get_kpis`, `get_recent_runs`, `get_active_jobs`), each independently querying the database — no shared transaction or consistency guarantee across them; under concurrent writes (e.g. the background worker completing a job mid-request), the KPI totals and the recent-runs table could reflect slightly different points in time. Low practical impact given SQLite/Azure SQL read consistency, but worth noting for a future consistency-sensitive feature.

**Change Impact** — Depends entirely on `web/queries.py`'s three read functions; changing their return shape breaks `home.html` silently (Jinja2 doesn't fail loudly on a missing dict key, it just renders blank).

**Callers** — none (top-level HTTP entry point)
**Calls** — M-010 (`render`, `require_login`, `sidebar_context`), M-011 (`get_kpis`, `get_recent_runs`, `get_active_jobs`)
**Integration Points Used** — none directly
