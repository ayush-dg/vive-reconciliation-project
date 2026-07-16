"""
auth.py

Session-based login. One hardcoded user for this phase — see
docs/VIVE_Implementation_Context.md Phase 3 (per-user logins are planned
later; a single shared account is sufficient for now).
"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from web.deps import render

router = APIRouter()

VALID_EMAIL = "admin@vive.com"
VALID_PASSWORD = "Vive@2026"


@router.get("/login")
def login_form(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    if email == VALID_EMAIL and password == VALID_PASSWORD:
        request.session["user"] = email
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", {"error": "Invalid email or password."}, status_code=401)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
