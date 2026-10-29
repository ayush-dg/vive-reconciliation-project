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

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from web.deps import LoginRequired
from web.routers import auth, batches, dashboard, exceptions, intake_trigger, jobs, mailbox_sync, netsuite_connect, reports, review_queue, statements, upload, users, validation
from web.worker import start_worker, stop_workers


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_worker()
    yield
    stop_workers()


app = FastAPI(title="VIVE Reconciliation", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("WEB_SESSION_SECRET", "vive-dev-secret-change-me"),
)

class _GZipExceptStatementPdfs:
    """Pages and their data compressed (2026-10-29: Statement Processing was
    353 KB, Exceptions 288 KB, sent as-is), except the statement PDF routes
    (/statements/...) -- PDFs are already compressed, and the side PDF
    viewer streams them as they are."""

    def __init__(self, app):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=1000)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").startswith("/statements/"):
            await self.app(scope, receive, send)
        else:
            await self.gzip(scope, receive, send)


app.add_middleware(_GZipExceptStatementPdfs)


class _VersionedStaticFiles(StaticFiles):
    """A versioned static file (static_url()'s ?v=<content hash>, web/deps.py)
    is cached by the browser for a year (2026-10-29): its URL changes
    whenever its content does, so it never needs re-checking. Unversioned
    URLs keep the default (re-checked)."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if b"v=" in (scope.get("query_string") or b"") and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", _VersionedStaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    # Remember the page they were trying to open (GETs only, a path taken
    # from the request itself -- never client-supplied) so login can send
    # them there, e.g. from a NetSuite statement-PDF link.
    if request.method == "GET":
        request.session["next"] = request.url.path
    return RedirectResponse("/login", status_code=303)


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(exceptions.router)
app.include_router(review_queue.router)
app.include_router(upload.router)
app.include_router(mailbox_sync.router)
app.include_router(reports.router)
app.include_router(validation.router)
app.include_router(users.router)
app.include_router(jobs.router)
app.include_router(intake_trigger.router)
app.include_router(batches.router)
app.include_router(statements.router)
app.include_router(netsuite_connect.router)
