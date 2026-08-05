## G02 — web shared deps
ID: M-010
Layer: infra
Source file: web/deps.py

**Module** — web shared deps
**ID** — M-010
**Layer** — infra
**Primary Responsibility** — Shared FastAPI dependencies for every router: Jinja2 template environment (with custom filters), the `require_login` auth guard, and the sidebar context builder.

**Inputs** — N/A (library module, not an HTTP entry point). Reads `request.session` for `require_login`/`sidebar_context`.

**Outputs** — `render()` returns a `TemplateResponse`; `require_login()` returns the session's user email or raises; `sidebar_context()` returns a dict merged into every page's template context.

**Public Interface**
- `class LoginRequired(Exception)` — raised by `require_login`, caught by `web/app.py`'s global handler.
- `require_login(request: Request) -> str`
- `sidebar_context(request: Request) -> dict` — `{open_exceptions_count, pending_review_count, user_email, user_name}`
- `render(request, name, ctx=None, status_code=200) -> TemplateResponse`
- Template filters registered on `templates.env.filters`: `money`, `money_signed`, `money_short`, `period_label`, `initials`, `friendly_dt`, `friendly_date`, `urlname`.

**Error Behaviour** — `friendly_date()`/`friendly_dt()` both catch `ValueError` from failed date-format parsing and fall back to returning the raw string unmodified rather than raising — a malformed date value degrades to ugly-but-harmless display rather than a 500. `sidebar_context()` has no error handling of its own; a failure in either underlying query call propagates.

**Known Fragility**
- `friendly_dt()` hardcodes `IST = timezone(timedelta(hours=5, minutes=30))` — the display timezone is hardcoded to India Standard Time regardless of deployment region or user preference, confirmed by direct code read (module-level constant, no config). If VIVE's actual AP team is not IST-based, every timestamp shown in the dashboard is silently wrong by however many hours — worth flagging for engineer confirmation, not assumed to be a bug (could be intentional if the dev/ops team is IST-based).
- `sidebar_context()` performs two live COUNT queries (`get_open_exceptions_count`, `get_pending_review_count`) on *every* page render across the entire app (imported by every router) — a real per-request cost, not cached.

**Change Impact** — Any new template filter needed by a future page must be added here (no per-template filter registration mechanism exists). Changing `sidebar_context()`'s returned keys affects every template's base layout (`base.html`) simultaneously.

**Callers** — M-001 through M-008 (every serving-layer router imports `render`/`require_login`/`sidebar_context`), M-009 (`LoginRequired`)
**Calls** — M-011 (`get_open_exceptions_count`, `get_pending_review_count`, imported lazily inside `sidebar_context()`)
**Integration Points Used** — none directly
