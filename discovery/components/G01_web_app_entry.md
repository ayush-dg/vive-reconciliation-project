## G01 — web app entry
ID: M-009
Layer: infra
Source file: web/app.py

**Module** — web app entry
**ID** — M-009
**Layer** — infra
**Primary Responsibility** — FastAPI application assembly: loads `.env`, constructs the app, wires session middleware, mounts static files, registers all 8 routers, and starts the background worker on lifespan startup.

**Inputs** — None at the HTTP level (this module has no routes of its own). Reads `WEB_SESSION_SECRET` env var (falls back to a hardcoded dev default `"vive-dev-secret-change-me"` if unset).

**Outputs** — The assembled `app` FastAPI instance; side effect of starting the background worker thread (via `start_worker()`) at lifespan startup.

**Public Interface**
- `app` (module-level `FastAPI` instance) — the actual ASGI entry point, imported by `web/start.py` and `startup.sh` as `web.app:app`.
- `lifespan(app)` — async context manager, calls `start_worker()` on entry.
- `login_required_handler(request, exc)` — global exception handler for `LoginRequired`, redirects to `/login`.

**Error Behaviour** — No explicit error handling for router registration or static-mount failures — either would raise at import time and prevent the app from starting at all (STARTUP-FATAL, consistent with TOPOLOGY.md's startup sequence). `LoginRequired` is the only exception type this module handles explicitly, converting it to a 303 redirect application-wide.

**Known Fragility** — **`WEB_SESSION_SECRET` defaults to a hardcoded, publicly-visible string in source** if the env var is unset — a real security concern for session integrity if ever deployed without setting this explicitly (distinct from, but same category of risk as, the hardcoded auth fallback credential in M-001). Worth a RISK_REGISTER entry alongside that one.

**Change Impact** — Adding a new router requires both creating it and registering it here (`app.include_router(...)`) — no auto-discovery mechanism; a new router file with no registration line here is simply unreachable, with no error or warning.

**Callers** — none (process entry point)
**Calls** — M-001 through M-008 (router registration), M-013 (`start_worker`), M-010 (imports `LoginRequired`)
**Integration Points Used** — none directly
