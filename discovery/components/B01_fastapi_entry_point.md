## B01 — FastAPI Entry Point
ID: M-001
Layer: serving
Source file: `web/app.py`

**Module** — FastAPI Entry Point
**ID** — M-001
**Layer** — serving
**Primary Responsibility** — Constructs the FastAPI app, wires session middleware/static files/all 10 routers, and starts/stops the background worker pool on the app lifespan.

**Inputs**
- `.env` file at `PROJECT_ROOT/.env` (explicit path, Rule 4) — sets `WEB_SESSION_SECRET` and every downstream env var the pipeline reads.
- HTTP requests, routed to the 10 mounted routers.

**Outputs**
- The `app` ASGI object uvicorn serves.
- Side effect: `start_worker()`/`stop_workers()` (M-005) called at lifespan startup/shutdown.
- Side effect: mounts `/static` from `web/static/`.

**Public Interface**
- `app` — module-level `FastAPI` instance, the only thing consumed externally (by `web/start.py`, M-004).
- `lifespan(app)` — async context manager, not called directly by other modules.
- `login_required_handler(request, exc)` — exception handler for `LoginRequired` (raised by M-002), redirects to `/login`.

**Error Behaviour**
- A router import failure (any of M-006–M-015) is STARTUP-FATAL — the module-level `from web.routers import ...` raises before `app` is ever constructed.
- `WEB_SESSION_SECRET` unset falls back to a hardcoded dev string (`"vive-dev-secret-change-me"`) rather than failing — a silent security downgrade, not a crash.
- `LoginRequired` from any route dependency is caught globally and converted to a 303 redirect to `/login`.

**Known Fragility**
- The fallback session secret is a real risk if this ever reaches a shared/production deployment without `WEB_SESSION_SECRET` set explicitly — no startup check enforces its presence.
- Router registration order matters for two routes inside M-008 (see B08) — this file's `include_router` calls are not the source of that ordering constraint, but a reordering here that changed router mount order would not itself fix or break it (ordering is within `web/routers/exceptions.py`, not across routers).

**Change Impact**
- Any change to `lifespan()` risks the worker pool (M-005) never starting or never stopping cleanly on shutdown.
- Removing a router's `include_router()` call silently removes an entire feature surface with no error — nothing verifies all 10 are mounted.

**Callers** — none (top-level ASGI entry point, invoked by uvicorn via M-004)
**Calls** — M-005 (start_worker/stop_workers), M-002 (LoginRequired exception type), M-006, M-007, M-008, M-009, M-010, M-011, M-012, M-013, M-014, M-015 (router registration)
**Integration Points Used** — none directly
