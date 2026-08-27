## B06 — Auth Router
ID: M-006
Layer: serving
Source file: `web/routers/auth.py`

**Module** — Auth Router
**ID** — M-006
**Layer** — serving
**Primary Responsibility** — Session-based login/logout, backed by bcrypt-verified `users` table lookups with a hardcoded fallback credential.

**Inputs** — `email`/`password` form fields (POST `/login`).

**Outputs** — `request.session["user"]` / `request.session["user_name"]` set on success; session cleared on `/logout`.

**Public Interface**
- `GET /login`, `POST /login`, `GET /logout` — no functions called by other modules.

**Error Behaviour** — `_authenticate()` catches any exception from the `users` lookup (`except Exception: pass`) and falls through to the hardcoded fallback check — a DB error during login degrades to fallback-credential-only auth rather than a 500, silently.

**Known Fragility**
- `FALLBACK_EMAIL`/`FALLBACK_PASSWORD`/`FALLBACK_NAME` constants are a real, currently-live authentication bypass — kept deliberately per the module docstring "until database-backed users are confirmed working end to end," with no tracked removal trigger or date. Confirmed present this session, unchanged from the archived record (R-007).
- Session `user` value is normalized (stripped/lowercased); any other code path reading `request.session["user"]` and comparing it against a differently-cased `users.email` value would silently fail to match.

**Change Impact** — Removing the fallback without confirming DB-backed login works in every deployment environment risks locking out all users if `users` table access fails for any reason.

**Callers** — M-001 (router registration)
**Calls** — M-002 (`render`), M-003 (`get_user_by_email`)
**Integration Points Used** — none
