## B10 — Reports Router
ID: M-010
Layer: serving
Source file: `web/routers/reports.py`

**Module** — Reports Router
**ID** — M-010
**Layer** — serving
**Primary Responsibility** — Reconciliation run list and per-statement report detail page.

**Inputs** — `statement_id` path param on the detail route.

**Outputs** — Renders `reports.html` / `report_detail.html`.

**Public Interface** — `GET /reports`, `GET /reports/{statement_id}` — no functions called by other modules.

**Error Behaviour** — Detail route redirects to `/reports` (303) if `get_statement_report()` finds no summary row — not a 404, a redirect.

**Known Fragility** — No fragility beyond what M-003's `get_statement_report()`/`get_all_runs()` already carry (see B03) — this router is a thin pass-through with no logic of its own.

**Change Impact** — Isolated to the reports pages.

**Callers** — M-001 (router registration)
**Calls** — M-002 (`render`, `require_login`, `sidebar_context`), M-003 (`get_all_runs`, `get_statement_report`)
**Integration Points Used** — none
