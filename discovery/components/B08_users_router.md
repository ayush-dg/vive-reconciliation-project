## B08 — users router
ID: M-008
Layer: serving
Source file: web/routers/users.py

**Module** — users router
**ID** — M-008
**Layer** — serving
**Primary Responsibility** — User list/add/remove management page. No role-based access control — any logged-in user can reach and use it.

**Inputs**
- `GET /users` — no inputs.
- `POST /users/add` — form fields `name`, `email`, `password` (all required).
- `POST /users/remove` — form field `email` (required).

**Outputs** — Writes to `users` table via `queries.create_user()` (bcrypt-hashes the password before insert) and `queries.delete_user_by_email()`. Renders `users.html` with the current user list and any error.

**Public Interface**
- `users_list(request, user) -> TemplateResponse` — `GET /users`
- `users_add(request, user, name, email, password) -> TemplateResponse | RedirectResponse` — `POST /users/add`
- `users_remove(request, user, email) -> TemplateResponse | RedirectResponse` — `POST /users/remove`

**Error Behaviour** — Explicit validation before writes: all-fields-required check (400 + re-rendered form on failure), duplicate-email check via `queries.get_user_by_email()` (400 on conflict), and a self-removal guard (`email == user.strip().lower()` → 400, "You cannot remove your own account"). No handling around the `bcrypt.hashpw()` call itself (CPU-bound, effectively cannot fail under normal operation) or around the DB write — a genuine DB error on add/remove propagates as an unhandled 500.

**Known Fragility** — No role-based access control at all (confirmed by source, matching RULE-08's flat-permission design intent, even though RULE-08 predates this page's existence) — any authenticated user, including one added by another non-admin user, can add or remove any other user (except themselves). This is explicitly a design choice, not an oversight, per docstring and RULE-08's rationale ("everyone using the dashboard does the same job today") — but worth flagging that the *scope* of "any user" now includes user-management itself, which RULE-08 may not have anticipated when written.

**Change Impact** — Depends on `queries.create_user()`/`get_user_by_email()`/`delete_user_by_email()`'s exact signatures; a schema change to `users` (e.g. adding a role column) would require this router to actually enforce it — currently nothing here would break, but nothing would use it either.

**Callers** — none (top-level HTTP entry point)
**Calls** — M-010 (`render`, `require_login`, `sidebar_context`), M-011 (`list_users`, `get_user_by_email`, `create_user`, `delete_user_by_email`)
**Integration Points Used** — none directly
