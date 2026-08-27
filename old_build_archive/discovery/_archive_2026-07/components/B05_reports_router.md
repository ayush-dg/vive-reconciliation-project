## B05 — reports router
ID: M-005
Layer: serving
Source file: web/routers/reports.py

**Module** — reports router
**ID** — M-005
**Layer** — serving
**Primary Responsibility** — Full list of reconciliation runs and per-statement report detail.

**Inputs** — `GET /reports` — no inputs. `GET /reports/{statement_id}` — path param `statement_id`.

**Outputs** — Renders `reports.html` (all runs, via `queries.get_all_runs()`) or `report_detail.html` (one statement's full summary/matched/exceptions data, via `queries.get_statement_report()`). Redirects to `/reports` (303) if the statement_id has no summary. No writes.

**Public Interface**
- `reports_list(request, user) -> TemplateResponse` — `GET /reports`
- `report_detail(statement_id, request, user) -> TemplateResponse | RedirectResponse` — `GET /reports/{statement_id}`

**Error Behaviour** — Explicit guard: `if not data["summary"]: return RedirectResponse("/reports", 303)` — a nonexistent or unreconciled statement_id degrades gracefully rather than raising or 404ing. No other explicit error handling; other exceptions propagate as unhandled 500s.

**Known Fragility** — None specific to this module beyond its full dependency on `queries.get_statement_report()`'s exact dict shape (`data["summary"]` plus whatever else that function returns, spread via `**data` into the template context) — a change to that function's keys silently changes template rendering.

**Change Impact** — Tightly coupled to `web/queries.py`'s `get_statement_report()` return shape.

**Callers** — none (top-level HTTP entry point)
**Calls** — M-010 (`render`, `require_login`, `sidebar_context`), M-011 (`get_all_runs`, `get_statement_report`)
**Integration Points Used** — none directly
