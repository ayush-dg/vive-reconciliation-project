"""
users.py

User management — list, add, remove. Every logged-in user can see the list;
only admins (web/deps.py is_admin(): the ADMIN_EMAILS app setting plus the
fallback admin login) can add or remove users. The server checks this on
every add/remove, not just the page, so a hand-made POST is refused too.

Locations (2026-11-09): admins also set the VIVE shops each user works
(web/user_locations.py) -- when adding the user, or later with "Edit
locations". Users cannot change their own. /location-scope is the
"My locations / All locations" switch on Home, Statement Processing and
Exceptions; any logged-in user may use it.
"""

from typing import List

import bcrypt
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from web.deps import is_admin, render, require_login, sidebar_context
from web import queries
from web import user_locations as ul

router = APIRouter()

ADMINS_ONLY = "Only admins can add or remove users."


def _users_ctx(request: Request, user: str, error: str = None, notice: str = None) -> dict:
    users = queries.list_users()
    shops_by_user = ul.all_user_shops()
    for u in users:
        u["shops"] = shops_by_user.get((u.get("email") or "").lower(), [])
    return {
        "active_page": "users",
        "users": users,
        "error": error,
        "notice": notice,
        "can_manage_users": is_admin(user),
        "shop_choices": ul.known_shops(),
        **sidebar_context(request),
    }


def _refuse(request: Request, user: str):
    return render(request, "users.html", _users_ctx(request, user, ADMINS_ONLY), status_code=403)


@router.get("/users")
def users_list(request: Request, user: str = Depends(require_login)):
    return render(request, "users.html", _users_ctx(request, user))


@router.post("/users/add")
def users_add(request: Request, user: str = Depends(require_login),
              name: str = Form(...), email: str = Form(...), password: str = Form(...),
              shops: List[str] = Form([])):
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
    if shops:
        ul.set_user_shops(email, shops, set_by=user)
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
    ul.delete_user_shops(email)
    return RedirectResponse("/users", status_code=303)


@router.post("/users/locations")
def users_locations(request: Request, user: str = Depends(require_login),
                    email: str = Form(...), shops: List[str] = Form([])):
    """Replaces a user's shops (admins only). None ticked = sees every location."""
    if not is_admin(user):
        return _refuse(request, user)
    email = email.strip().lower()
    if not queries.get_user_by_email(email):
        return render(request, "users.html", _users_ctx(request, user, f"No user {email}."), status_code=400)
    saved = ul.set_user_shops(email, shops, set_by=user)
    notice = (f"{email} now sees {len(saved)} location{'s' if len(saved) != 1 else ''}: {', '.join(saved)}."
              if saved else f"{email} has no locations set, so they see every location.")
    return render(request, "users.html", _users_ctx(request, user, notice=notice))


@router.get("/location-scope")
def location_scope_switch(request: Request, user: str = Depends(require_login), value: str = "",
                          next: str = "/"):
    """The My / All locations switch: remembers the choice until logout (the
    login session) and goes back to the page it was clicked on."""
    request.session[ul.SCOPE_SESSION_KEY] = ul.SCOPE_ALL if value == ul.SCOPE_ALL else ul.SCOPE_MINE
    return RedirectResponse(ul.safe_next(next), status_code=303)
