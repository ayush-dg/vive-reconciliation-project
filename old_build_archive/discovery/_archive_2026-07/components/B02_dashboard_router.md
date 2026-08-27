## B02 — dashboard router
ID: M-002
Layer: serving
Source file: web/routers/dashboard.py
Rewritten: 2026-07-25 scoped BCE refresh (recent_batches added 2026-07-24, Step 11)

**Module** — dashboard router
**ID** — M-002
**Layer** — serving
**Primary Responsibility** — Home page: KPI totals, a table of recent reconciliation runs, and (**new**) a summary of the most recently completed Event Grid auto-intake batches.

**Inputs** — `GET /` — no inputs beyond an authenticated session (enforced via `Depends(require_login)`). Unchanged.

**Outputs** — Renders `home.html` with `kpis` (from `queries.get_kpis()`), `runs` (10 most recent, from `queries.get_recent_runs(limit=10)`), `active_jobs` (from `queries.get_active_jobs()`), **`recent_batches` (new — 3 most recent finished batches, from `queries.get_recent_completed_batches(limit=3)`)**, plus a formatted dashboard title/month label. No database writes.

**Public Interface**
- `home(request: Request, user: str = Depends(require_login)) -> TemplateResponse` — `GET /` — signature unchanged, one new context key added to its body.

**Error Behaviour** — No explicit error handling in this module; any exception from the now-four `queries` calls propagates as an unhandled FastAPI 500. `require_login` raises `LoginRequired`, caught globally by `web/app.py`'s exception handler (redirects to `/login`), not handled here. Unchanged.

**Known Fragility** — This route now calls **four** separate query functions (`get_kpis`, `get_recent_runs`, `get_active_jobs`, **`get_recent_completed_batches`**), each independently querying the database — no shared transaction or consistency guarantee across them; under concurrent writes (e.g. a worker-pool thread completing a job mid-request), the KPI totals, the recent-runs table, and now the recent-batches summary could each reflect slightly different points in time. Same low-practical-impact assessment as before, now spread across one more query. **New: `get_recent_completed_batches()` internally calls `get_all_batches()` and filters in Python** (see G03) — meaning this one dashboard context key is the most expensive of the four calls, re-deriving every batch's stats before taking the first 3; not a problem at current batch volume, worth revisiting if batch history grows large.

**Change Impact** — Depends entirely on `web/queries.py`'s read functions; changing their return shape breaks `home.html` silently (Jinja2 doesn't fail loudly on a missing dict key, it just renders blank) — unchanged, now also true for `recent_batches`.

**Callers** — none (top-level HTTP entry point)
**Calls** — M-010 (`render`, `require_login`, `sidebar_context`), M-011 (`get_kpis`, `get_recent_runs`, `get_active_jobs`, **`get_recent_completed_batches`, new**)
**Integration Points Used** — none directly
