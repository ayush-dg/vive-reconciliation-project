## B02 — Shared Web Dependencies
ID: M-002
Layer: serving
Source file: `web/deps.py`

**Module** — Shared Web Dependencies
**ID** — M-002
**Layer** — serving
**Primary Responsibility** — Provides Jinja2 template rendering (with registered formatting filters), the `require_login` FastAPI dependency, and the sidebar context every page needs.

**Inputs**
- `request.session["user"]` (set by M-006 on login) — read by `require_login()`.
- Raw values passed into each template filter (money, dates, names) from whatever router context calls them.

**Outputs**
- `templates` — module-level `Jinja2Templates` instance with 7 registered filters (`money`, `money_signed`, `money_short`, `period_label`, `initials`, `friendly_dt`, `friendly_date`, `urlname`).
- `render()` — thin wrapper returning a `TemplateResponse`.
- `sidebar_context()` — dict with open-exception/pending-review counts and the current user's display name, spread into nearly every page's template context.

**Public Interface**
- `render(request, name, ctx=None, status_code=200)`
- `require_login(request) -> str` — FastAPI dependency, raises `LoginRequired` if no session user.
- `sidebar_context(request) -> dict`
- `LoginRequired` — exception class, caught by M-001's app-level handler.
- Template filters: `money`, `money_signed`, `money_short`, `period_label`, `initials`, `friendly_date`, `friendly_dt`, `urlname`.

**Error Behaviour**
- `require_login()` never returns an error response itself — it raises `LoginRequired`, which only M-001's registered exception handler converts into a redirect. A router that used this dependency without that handler registered would 500.
- Every filter is defensive against `None`/malformed input (falls back to `"—"`, `"??"`, or the raw string) — no filter raises on bad data.

**Known Fragility**
- `friendly_dt()` hardcodes IST (`timezone(timedelta(hours=5, minutes=30))`) for every displayed timestamp, regardless of the deployment's actual audience timezone — confirmed still present, not yet fixed (see `TOPOLOGY.md`, archived `RISK_REGISTER.md` R-011). A future engineer adding a new timestamp display inherits this without any signal that it's wrong for a non-IST audience.
- `sidebar_context()` does two extra DB round-trips (`get_open_exceptions_count()`, `get_pending_review_count()`) on every single page render across the app — no caching. A significant, uncounted per-request cost multiplier if page volume grows.

**Change Impact**
- Any filter signature change (e.g. `money`) breaks every template that uses it — no compile-time check, only a runtime Jinja2 error on the next render of an affected page.
- `sidebar_context()`'s dict shape is spread with `**sidebar_context(request)` into nearly every router's context — adding/renaming a key here is a fan-out change across all 10 routers' templates.

**Callers** — M-006, M-007, M-008, M-009, M-010, M-011, M-012, M-013, M-014 (every router except M-015, which has no login-gated UI)
**Calls** — M-003 (`get_open_exceptions_count()`, `get_pending_review_count()`, imported lazily inside `sidebar_context()`)
**Integration Points Used** — none
