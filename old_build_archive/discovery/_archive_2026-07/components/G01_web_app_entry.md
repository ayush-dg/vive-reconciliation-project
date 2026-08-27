## G01 — web app entry
ID: M-009
Layer: infra
Source file: web/app.py
Rewritten: 2026-07-25 scoped BCE refresh (two new routers + graceful worker shutdown added 2026-07-24)

**Module** — web app entry
**ID** — M-009
**Layer** — infra
**Primary Responsibility** — FastAPI application assembly: loads `.env`, constructs the app, wires session middleware, mounts static files, registers all **10** routers (was 8), starts the background worker **pool** on lifespan startup, and (**new**) stops it gracefully on lifespan shutdown.

**Inputs** — None at the HTTP level (this module has no routes of its own). Reads `WEB_SESSION_SECRET` env var (falls back to a hardcoded dev default `"vive-dev-secret-change-me"` if unset) — unchanged.

**Outputs** — The assembled `app` FastAPI instance; side effect of starting the background worker pool (via `start_worker()`) at lifespan startup and, **new as of 2026-07-24**, stopping it (via `stop_workers()`) at lifespan shutdown — previously nothing ran on shutdown at all.

**Public Interface**
- `app` (module-level `FastAPI` instance) — the actual ASGI entry point, imported by `web/start.py` and `startup.sh` as `web.app:app`. Unchanged.
- `lifespan(app)` — async context manager, calls `start_worker()` on entry **and now `stop_workers()` after `yield`, on shutdown (new)**.
- `login_required_handler(request, exc)` — global exception handler for `LoginRequired`, redirects to `/login`. Unchanged.
- **Router registrations extended:** `app.include_router(intake_trigger.router)` and `app.include_router(batches.router)` added alongside the original 8.

**Error Behaviour** — No explicit error handling for router registration or static-mount failures — either would raise at import time and prevent the app from starting at all (STARTUP-FATAL) — unchanged, now also true for the two new routers. `LoginRequired` remains the only exception type this module handles explicitly.

**Known Fragility**
- **`WEB_SESSION_SECRET` defaults to a hardcoded, publicly-visible string in source** if the env var is unset — unchanged, not touched by this session's work; still tracked as `discovery/RISK_REGISTER.md` R-008.
- **New: `stop_workers()` at shutdown has no timeout passed** (`stop_workers()` called with no arguments, so `web/worker.py`'s default `timeout=None` applies) — a worker thread mid-job at shutdown time will run to completion (up to the pipeline's own 30-minute subprocess timeout) before the app process can actually exit. This is a deliberate tradeoff for not losing an in-flight job, not an oversight, but worth knowing if a deployment's shutdown/restart tooling assumes a fast exit.

**Change Impact** — Adding a new router requires both creating it and registering it here (`app.include_router(...)`) — no auto-discovery mechanism; unchanged, now demonstrated twice more by the 2026-07-24 additions (`intake_trigger`, `batches`).

**Callers** — none (process entry point)
**Calls** — M-001 through M-008 (router registration), **M-045, M-046 (router registration, new)**, M-013 (`start_worker`, **and `stop_workers`, new**), M-010 (imports `LoginRequired`)
**Integration Points Used** — none directly
