## B05 — Background Worker Pool
ID: M-005
Layer: serving
Source file: `web/worker.py`

**Module** — Background Worker Pool
**ID** — M-005
**Layer** — serving
**Primary Responsibility** — Runs a configurable pool of daemon threads (default 3) that each poll the `jobs` table every 30s, claim a PENDING job atomically, and run the pipeline against it as a subprocess.

**Inputs**
- `VIVE_WORKER_POOL_SIZE` env var (default 3).
- `jobs` table rows via `claim_next_pending_job()` (M-003).

**Outputs**
- Subprocess execution of `scripts/run_full_pipeline.py` (M-021) per claimed job.
- `jobs` row updates (`status`, `started_at`/`completed_at`, `statement_id`, `vendor_name`, `error_message`) via M-003.

**Public Interface**
- `start_worker()` — idempotent (guarded by `_worker_started` + `_start_lock`), spawns `_pool_size()` daemon threads.
- `stop_workers(timeout=None)` — signals `_shutdown_event`, joins every thread.

**Error Behaviour**
- `_worker_loop()` wraps its per-iteration body in `try/except Exception: traceback.print_exc()` — no exception ever kills a worker thread.
- `_run_job()` catches its own exceptions around the subprocess call and around the failure-path `update_job_status()` call itself (`except Exception: pass`) — a logging failure on the failure path is silently swallowed, by design, so it never masks the original error or crashes the loop.
- Subprocess timeout is a hard 1800s (30 min) — `subprocess.run(..., timeout=1800)` raises `TimeoutExpired`, caught by the same outer `except Exception`, recorded as a FAILED job with a generic worker-error message (not the specific timeout reason surfaced distinctly).

**Known Fragility**
- No stale-job requeue exists — if a job is stuck PROCESSING (process killed externally, machine restarted mid-run), nothing ever reclaims it; `claim_next_pending_job()`'s guard means only that same `pdf_filename` is blocked, not the whole queue, but that one file is stuck until a human intervenes.
- `VENV_PYTHON` path assumes a `venv/Scripts/python.exe` layout (Windows venv) — falls back to `sys.executable` if absent, but a differently-named/located virtual environment silently uses whichever Python launched the web app instead of a possibly-different pipeline-specific environment.
- `_shutdown_event.wait(POLL_INTERVAL_SECONDS)` is only checked between jobs — a worker mid-subprocess-run does not respond to shutdown until that subprocess completes or times out (up to 30 minutes), so `stop_workers()` can block for a long time under load.

**Change Impact** — Any change to `claim_next_pending_job()`'s atomicity guarantee (in M-003) directly risks this module's core correctness claim (no two workers double-processing the same PDF).

**Callers** — M-001 (`start_worker()`/`stop_workers()` from `lifespan()`)
**Calls** — M-003 (`claim_next_pending_job()`, `update_job_status()`, `get_vendor_name_for_statement()`), M-021 (via `subprocess.run`)
**Integration Points Used** — none directly (subprocess boundary to M-021, not an external system)
