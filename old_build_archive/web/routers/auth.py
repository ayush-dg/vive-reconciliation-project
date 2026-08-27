"""
auth.py

Session-based login, backed by the users table (see
migrations/004_add_users_table.sql) with bcrypt-verified passwords. The
original hardcoded admin/Vive@2026 credentials are kept as a fallback
deliberately — per the Phase 3 instructions, remove FALLBACK_EMAIL/
FALLBACK_PASSWORD/FALLBACK_NAME and _authenticate()'s fallback branch only
once database-backed users are confirmed working end to end.
"""

import bcrypt
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from web.deps import render
from web import queries

router = APIRouter()

FALLBACK_EMAIL = "admin@vive.com"
FALLBACK_PASSWORD = "Vive@2026"
FALLBACK_NAME = "Admin"


def _authenticate(email: str, password: str):
    """Returns the user's display name on success, else None."""
    try:
        user = queries.get_user_by_email(email)
        if user and user["is_active"] and bcrypt.checkpw(
            password.encode("utf-8"), user["password_hash"].encode("utf-8")
        ):
            return user["name"]
    except Exception:
        pass  # DB lookup failed (e.g. migration not yet run) — fall through

    if email == FALLBACK_EMAIL and password == FALLBACK_PASSWORD:
        return FALLBACK_NAME

    return None


@router.get("/login")
def login_form(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    name = _authenticate(email, password)
    if name:
        # Normalized (stripped/lowercased) so it matches what's stored in
        # the users table — kept consistent everywhere this session value
        # is compared against a users.email lookup (e.g. "remove yourself"
        # in web/routers/users.py).
        request.session["user"] = email.strip().lower()
        request.session["user_name"] = name
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", {"error": "Invalid email or password."}, status_code=401)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
