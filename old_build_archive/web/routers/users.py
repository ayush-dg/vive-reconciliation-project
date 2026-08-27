"""
users.py

User management — list, add, remove. No role-based access control yet
(any logged-in user can reach this page) — per the Phase 3 instructions,
just build the page for now.
"""

import bcrypt
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from web.deps import render, require_login, sidebar_context
from web import queries

router = APIRouter()


def _users_ctx(request: Request, error: str = None) -> dict:
    return {
        "active_page": "users",
        "users": queries.list_users(),
        "error": error,
        **sidebar_context(request),
    }


@router.get("/users")
def users_list(request: Request, user: str = Depends(require_login)):
    return render(request, "users.html", _users_ctx(request))


@router.post("/users/add")
def users_add(request: Request, user: str = Depends(require_login),
              name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    name = name.strip()

    if not name or not email or not password:
        return render(request, "users.html", _users_ctx(request, "All fields are required."), status_code=400)

    if queries.get_user_by_email(email):
        error = f"A user with email {email} already exists."
        return render(request, "users.html", _users_ctx(request, error), status_code=400)

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    queries.create_user(name=name, email=email, password_hash=password_hash, created_by=user)
    return RedirectResponse("/users", status_code=303)


@router.post("/users/remove")
def users_remove(request: Request, user: str = Depends(require_login), email: str = Form(...)):
    email = email.strip().lower()

    if email == user.strip().lower():
        error = "You cannot remove your own account."
        return render(request, "users.html", _users_ctx(request, error), status_code=400)

    queries.delete_user_by_email(email)
    return RedirectResponse("/users", status_code=303)
