"""
users.py

User management — list, add, remove. Every logged-in user can see the list;
only admins (web/deps.py is_admin(): the ADMIN_EMAILS app setting plus the
fallback admin login) can add or remove users. The server checks this on
every add/remove, not just the page, so a hand-made POST is refused too.
"""

import bcrypt
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from web.deps import is_admin, render, require_login, sidebar_context
from web import queries

router = APIRouter()

ADMINS_ONLY = "Only admins can add or remove users."


def _users_ctx(request: Request, user: str, error: str = None) -> dict:
    return {
        "active_page": "users",
        "users": queries.list_users(),
        "error": error,
        "can_manage_users": is_admin(user),
        **sidebar_context(request),
    }


def _refuse(request: Request, user: str):
    return render(request, "users.html", _users_ctx(request, user, ADMINS_ONLY), status_code=403)


@router.get("/users")
def users_list(request: Request, user: str = Depends(require_login)):
    return render(request, "users.html", _users_ctx(request, user))


@router.post("/users/add")
def users_add(request: Request, user: str = Depends(require_login),
              name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    if not is_admin(user):
        return _refuse(request, user)

    email = email.strip().lower()
    name = name.strip()

    if not name or not email or not password:
        return render(request, "users.html", _users_ctx(request, user, "All fields are required."), status_code=400)

    if queries.get_user_by_email(email):
        error = f"A user with email {email} already exists."
        return render(request, "users.html", _users_ctx(request, user, error), status_code=400)

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    queries.create_user(name=name, email=email, password_hash=password_hash, created_by=user)
    return RedirectResponse("/users", status_code=303)


@router.post("/users/remove")
def users_remove(request: Request, user: str = Depends(require_login), email: str = Form(...)):
    if not is_admin(user):
        return _refuse(request, user)

    email = email.strip().lower()

    if email == user.strip().lower():
        error = "You cannot remove your own account."
        return render(request, "users.html", _users_ctx(request, user, error), status_code=400)

    queries.delete_user_by_email(email)
    return RedirectResponse("/users", status_code=303)
