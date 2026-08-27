## B13 — Users Router
ID: M-013
Layer: serving
Source file: `web/routers/users.py`

**Module** — Users Router
**ID** — M-013
**Layer** — serving
**Primary Responsibility** — User list/add/remove, with no role-based access control — any logged-in user can manage any other user.

**Inputs** — `name`/`email`/`password` form fields (add); `email` form field (remove).

**Outputs** — Writes via M-003's `create_user()`/`delete_user_by_email()`; renders `users.html`.

**Public Interface** — `GET /users`, `POST /users/add`, `POST /users/remove` — no functions called by other modules.

**Error Behaviour** — Missing fields or a duplicate email on add renders the page with a 400 and an inline error, not an exception. Self-removal is explicitly blocked with a 400, comparing the normalized session email against the normalized form email.

**Known Fragility** — No RBAC of any kind — confirmed still true this session, consistent with RULE-08's flat-permission design intent. Any authenticated user can add or remove any other user, including presumably an admin, with the sole guard being "cannot remove yourself."

**Change Impact** — Introducing role tiers would require changes here plus every other router's `require_login` dependency (M-002) to become role-aware — currently a single flat authorization model system-wide.

**Callers** — M-001 (router registration)
**Calls** — M-002 (`render`, `require_login`, `sidebar_context`), M-003 (`list_users`, `get_user_by_email`, `create_user`, `delete_user_by_email`)
**Integration Points Used** — none
