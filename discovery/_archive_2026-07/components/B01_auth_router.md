## B01 — auth router
ID: M-001
Layer: serving
Source file: web/routers/auth.py

**Module** — auth router
**ID** — M-001
**Layer** — serving
**Primary Responsibility** — Session-based login/logout for the web dashboard, backed by the `users` table with a hardcoded fallback credential.

**Inputs**
- `GET /login` — no inputs; renders the login form unless a session already exists (redirects to `/` if so).
- `POST /login` — form fields `email: str`, `password: str` (both required, FastAPI `Form(...)`).
- `GET /logout` — no inputs.

**Outputs**
- Sets `request.session["user"]` (normalized: stripped, lowercased) and `request.session["user_name"]` on successful login.
- Redirects to `/` on success, `/login` on failure (401) or logout (303).
- No database writes — this module only reads (`queries.get_user_by_email`).

**Public Interface**
- `login_form(request: Request) -> TemplateResponse` — `GET /login`
- `login_submit(request: Request, email: str, password: str) -> RedirectResponse` — `POST /login`
- `logout(request: Request) -> RedirectResponse` — `GET /logout`
- `_authenticate(email: str, password: str) -> Optional[str]` — internal; returns display name on success

**Error Behaviour**
- `_authenticate()`: any exception from `queries.get_user_by_email()` (e.g. `users` table missing — see F01 divergence, now resolved) is caught and swallowed (`except Exception: pass`), falling through to the hardcoded fallback check rather than propagating. A genuine DB error is silently treated the same as "user not found."
- Failed login returns HTTP 401 with a generic "Invalid email or password" message — does not distinguish wrong email from wrong password (standard practice, not a bug).
- No error handling needed for logout — `request.session.clear()` cannot raise in a way this code catches.

**Known Fragility**
- **Hardcoded fallback credential** (`FALLBACK_EMAIL = "admin@vive.com"`, `FALLBACK_PASSWORD`, module-level constants — values intentionally not reproduced in this artifact, see file directly). The module's own docstring says this should be removed "only once database-backed users are confirmed working end-to-end" — as of this session it is still present and still functions as a working login path independent of the `users` table. This is the RISK_REGISTER candidate already flagged in Session A0/A.
- The broad `except Exception: pass` around the real user lookup means *any* failure mode of the users table (missing table, connection drop, schema mismatch) degrades silently to "try the fallback" rather than surfacing an operational error — a DBA investigating a login outage would see nothing in logs from this path.

**Change Impact** — Removing the fallback credential without first confirming every real user has a working `users` row would lock out anyone whose account setup is incomplete. Any change to `queries.get_user_by_email()`'s return shape (currently expects `is_active`, `password_hash` keys) must be mirrored here.

**Callers** — none (top-level HTTP entry point, reached only via `web/app.py`'s router registration)
**Calls** — M-010 (`web/deps.py`: `render`), M-011 (`web/queries.py`: `get_user_by_email`)
**Integration Points Used** — none directly (delegates DB access to M-011/M-033)
