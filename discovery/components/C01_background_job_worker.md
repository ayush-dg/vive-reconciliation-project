## C01 — background job worker
ID: M-013
Layer: pipeline
Source file: web/worker.py
Rewritten: 2026-07-25 scoped BCE refresh (single worker → pool, 2026-07-24 Step 5)

**Module** — background job worker
**ID** — M-013
**Layer** — pipeline
**Primary Responsibility** — A **pool** of daemon threads (`VIVE_WORKER_POOL_SIZE`, default 3 — a single thread prior to 2026-07-24), each independently started at app startup; each polls `jobs` for the oldest claimable PENDING row every 30s, runs it through the pipeline as a subprocess, records the outcome.

**Inputs** — None directly (each thread polls the database itself); `start_worker()` takes no arguments; pool size is read from `VIVE_WORKER_POOL_SIZE` at start time via `_pool_size()`.

**Outputs** — Updates `jobs.status` (PROCESSING → COMPLETED/FAILED), `statement_id`, `vendor_name`, `completed_at`, `error_message` via `queries.update_job_status()` — unchanged from the single-worker design; every thread writes through the same function.

**Public Interface**
- `start_worker()` — idempotent (guarded by `_worker_started` + `_start_lock`), spawns `_pool_size()` daemon threads once per process (was exactly one thread before 2026-07-24).
- `stop_workers(timeout=None)` — **new as of 2026-07-24, did not exist in the single-worker version.** Signals every thread to stop via `_shutdown_event`, then joins each (with an optional per-thread timeout). A thread mid-job always finishes that job first — the shutdown event is only checked between jobs, never used to interrupt a running subprocess. Safe to call even if the pool was never started. Called from `web/app.py`'s `lifespan()` on shutdown, which did not call anything equivalent before.
- `_worker_loop(worker_name)` (private) — infinite polling loop, `POLL_INTERVAL_SECONDS = 30`, now uses `_shutdown_event.wait(POLL_INTERVAL_SECONDS)` instead of a plain `time.sleep()` so a shutdown request wakes the loop immediately rather than after a full poll interval.
- `_run_job(job: dict)` (private) — runs one job via subprocess; unchanged in behavior from the single-worker version.
- `_pool_size()` (private, new) — reads `VIVE_WORKER_POOL_SIZE`, default `DEFAULT_WORKER_POOL_SIZE = 3`.

**Error Behaviour**
- **`_worker_loop()`'s outer `try/except Exception: traceback.print_exc()`** ensures a single bad iteration (e.g. a transient DB error on `claim_next_pending_job()`) never kills that thread's polling loop — unchanged from the single-worker design, now true independently per pool thread.
- **`_run_job()`'s subprocess call has a hard 1800s (30-minute) timeout** — a hung pipeline run is killed, not left running forever; the job is marked FAILED with the last 4000 chars of combined stdout/stderr. Unchanged.
- **Even the FAILURE-recording write is wrapped in its own `try/except Exception: pass`** — unchanged.
- **`STATEMENT_ID_RE` regex extraction is the only way this module learns the `statement_id`** a job produced — unchanged; still a fragile string contract with `scripts/run_full_pipeline.py`'s print output (see IC-18/R-005, neither touched by the 2026-07-24/25 changes).

**Known Fragility**
- **Atomic claiming is enforced by `claim_next_pending_job()` (M-011), not by this module — and that guard's scope changed underneath this module on 2026-07-24.** Until then, the guard refused to claim *anything* while any job anywhere was PROCESSING, which made a worker pool here pointless (extra threads would just poll and find nothing claimable). As of 2026-07-24, the guard is scoped to `pdf_filename` — see `discovery/INVARIANT_CATALOGUE.md`'s rewritten IC-19 — which is what makes a pool of more than one thread here actually do useful concurrent work: different statements can now process in parallel, up to `VIVE_WORKER_POOL_SIZE` at once, while two jobs for the *same* PDF still cannot race each other's `extraction_cache` write.
- **A second, independent concurrency cap now exists one layer down** — `VIVE_MAX_CONCURRENT_AI_CALLS` (M-047, `src/ai/concurrency_limiter.py`, see IC-21) bounds how many Claude Sonnet calls the pool's subprocesses can make at once, separately from `VIVE_WORKER_POOL_SIZE` bounding how many jobs can run at once. The two are independently configurable and can be sized differently — worth understanding as two separate dials, not one.
- **No liveness/watchdog on any individual worker thread** — unchanged from the single-worker design (see R-004); the pool means the *system* is more resilient to one thread dying (others continue independently), but no individual thread is monitored or restarted if its own `_worker_loop()` somehow exits (still only reachable via something not caught by `except Exception`, e.g. `SystemExit`).

**Change Impact** — Any change to `scripts/run_full_pipeline.py`'s printed output format must keep the exact `"Statement ID: <value>"` phrase intact, or this module's regex extraction silently breaks — unchanged. New: `VIVE_WORKER_POOL_SIZE` and `VIVE_MAX_CONCURRENT_AI_CALLS` should be considered together when tuning throughput — increasing the former without the latter just means more threads waiting on AI-call slots, not more actual extraction throughput.

**Callers** — none (invoked once by M-009 at app startup; `stop_workers()` invoked once by M-009 at app shutdown, new as of 2026-07-24)
**Calls** — M-011 (`claim_next_pending_job`, `update_job_status`, `get_vendor_name_for_statement`), M-018 (`scripts/run_full_pipeline.py`, via subprocess) — unchanged; the Claude Sonnet concurrency gate (M-047) is called from *within* that subprocess by M-023, not directly by this module
**Integration Points Used** — none directly (delegates all DB/pipeline work to what it calls)
