"""
app.py

FastAPI entry point for the VIVE Reconciliation web app. Run via
web/start.py (which invokes `uvicorn web.app:app --reload --port 8000`
from the project root).
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from web.deps import LoginRequired
from web.routers import auth, dashboard, exceptions, reports, upload, users

app = FastAPI(title="VIVE Reconciliation")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("WEB_SESSION_SECRET", "vive-dev-secret-change-me"),
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(exceptions.router)
app.include_router(upload.router)
app.include_router(reports.router)
app.include_router(users.router)
