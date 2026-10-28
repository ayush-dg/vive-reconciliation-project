"""
auth.py

Session-based login, backed by the users table (see
migrations/004_add_users_table.sql) with bcrypt-verified passwords.

Fallback admin login (2026-10-28): the credentials are no longer in the
code. ADMIN_LOGIN_EMAIL and ADMIN_LOGIN_PASSWORD come from the app settings;
with either unset there is no fallback and only users-table logins work. It
exists because an environment's users table can be empty (dev's was on
2026-10-28): log in with it, add real users on the Users page, then remove
the settings.
"""

import hmac
import os

import bcrypt
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from web.deps import render
from web import queries

router = APIRouter()

FALLBACK_NAME = "Admin"


def _fallback_login(email: str, password: str) -> bool:
    """True when the app settings define the fallback admin login and these
    credentials are it."""
    admin_email = (os.getenv("ADMIN_LOGIN_EMAIL") or "").strip().lower()
    admin_password = os.getenv("ADMIN_LOGIN_PASSWORD") or ""
    if not admin_email or not admin_password or (email or "").strip().lower() != admin_email:
        return False
    # Constant-time comparison, so response time says nothing about the password.
    return hmac.compare_digest((password or "").encode("utf-8"), admin_password.encode("utf-8"))


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

    if _fallback_login(email, password):
        return FALLBACK_NAME

    return None


def _post_login_destination(request: Request) -> str:
    """Where to send a user after login: the page that bounced them to
    /login (stored server-side by the LoginRequired handler), else the
    dashboard. Only a same-site absolute path is ever honoured."""
    target = request.session.pop("next", None) or "/"
    return target if target.startswith("/") and not target.startswith("//") else "/"


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
        return RedirectResponse(_post_login_destination(request), status_code=303)
    return render(request, "login.html", {"error": "Invalid email or password."}, status_code=401)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
