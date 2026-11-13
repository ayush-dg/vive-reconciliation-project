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
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from web.deps import LoginRequired
from web.routers import auth, batches, dashboard, exceptions, intake_trigger, jobs, mailbox_sync, netsuite_connect, reports, review_queue, statements, upload, users, validation
from web.worker import start_worker, stop_workers


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Live NetSuite reads go to a helper process with a pool of connections
    # (2026-11-13, src/netsuite/connect_helper.py); it starts on first use.
    from src.netsuite import connect_client, connect_helper
    connect_client.use_helper(True)
    start_worker()
    yield
    stop_workers()
    connect_helper.stop_helper()


app = FastAPI(title="VIVE Reconciliation", lifespan=lifespan)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    """Liveness for the App Service health check (2026-11-13): answered on the
    event loop itself -- no login, no database, no worker thread -- so it only
    fails when the app is truly frozen."""
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("ok", headers={"Cache-Control": "no-store"})

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


_DATABASE_DOWN_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Try again</title>
<meta http-equiv="refresh" content="10"></head>
<body style="font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;color:#1f2937">
<h1 style="font-size:1.25rem">The database didn't answer</h1>
<p>The connection to the database dropped and didn't come back after several tries.
This page reloads itself in 10 seconds, or <a href="">try again now</a>.</p>
</body></html>"""


try:
    import pyodbc
except ImportError:  # local SQLite-only setups
    pyodbc = None

if pyodbc is not None:
    @app.exception_handler(pyodbc.Error)
    async def database_error_handler(request: Request, exc: pyodbc.Error):
        # A connection that stayed down through every retry (fabric_sql /
        # connection.py) gets a "try again" page instead of a bare Internal
        # Server Error (2026-11-04). Any other database error is a real bug
        # and still goes through as a 500.
        from src.lakehouse.connection import _is_dropped_connection_error

        if not _is_dropped_connection_error(exc):
            raise exc
        print(f"[web] {request.method} {request.url.path}: database connection dropped -- {exc}")
        return HTMLResponse(_DATABASE_DOWN_PAGE, status_code=503, headers={"Retry-After": "10"})


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
