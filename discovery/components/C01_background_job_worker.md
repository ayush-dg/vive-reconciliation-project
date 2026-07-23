## C01 — background job worker
ID: M-013
Layer: pipeline
Source file: web/worker.py

**Module** — background job worker
**ID** — M-013
**Layer** — pipeline
**Primary Responsibility** — Daemon thread started at app startup; polls `jobs` for the oldest PENDING row every 30s, runs it through the pipeline as a subprocess, records the outcome.

**Inputs** — None directly (polls the database itself); `start_worker()` takes no arguments.

**Outputs** — Updates `jobs.status` (PROCESSING → COMPLETED/FAILED), `statement_id`, `vendor_name`, `completed_at`, `error_message` via `queries.update_job_status()`.

**Public Interface**
- `start_worker()` — idempotent (guarded by `_worker_started` + `_start_lock`), spawns the daemon thread once per process.
- `_worker_loop()` (private) — infinite polling loop, `POLL_INTERVAL_SECONDS = 30`.
- `_run_job(job: dict)` (private) — runs one job via subprocess.

**Error Behaviour**
- **`_worker_loop()`'s outer `try/except Exception: traceback.print_exc()`** ensures a single bad iteration (e.g. a transient DB error on `claim_next_pending_job()`) never kills the polling loop — confirmed by source, matching the module's own docstring claim "must never crash."
- **`_run_job()`'s subprocess call has a hard 1800s (30-minute) timeout** — a hung pipeline run is killed, not left running forever; the job is marked FAILED with the last 4000 chars of combined stdout/stderr.
- **Even the FAILURE-recording write is wrapped in its own `try/except Exception: pass`** — if `update_job_status()` itself fails (e.g. DB connection issue) while trying to record that the job failed, that secondary failure is silently swallowed rather than crashing the worker loop.
- **`STATEMENT_ID_RE` regex extraction is the only way this module learns the `statement_id`** a job produced — `re.compile(r"Statement ID:\s*(\S+)")` matched against the subprocess's combined output. If `scripts/run_full_pipeline.py`'s print format ever changes (e.g. the exact phrase "Statement ID:"), this silently stops finding a match and the job is marked FAILED even if the pipeline actually succeeded (confirmed: `if result.returncode != 0 or not match:` treats "no regex match" identically to "nonzero exit").

**Known Fragility**
- **Atomic single-job-at-a-time claiming is enforced by `claim_next_pending_job()` (M-011), not by this module** — this module's own resilience to multiple running instances (a "leftover dev server from an earlier session, or multiple uvicorn worker processes," per its own docstring) depends entirely on that other module's correctness.
- **No liveness/watchdog on the worker thread itself** — if `_worker_loop()`'s thread died for a reason not caught by its outer `try/except` (unlikely given the broad catch, but e.g. a `SystemExit` or `KeyboardInterrupt` wouldn't be caught by `except Exception`), nothing restarts it and no external monitor would know jobs stopped being processed. Confirmed as a real gap, not just theoretical — matches the "no stale-job requeue" finding already in TOPOLOGY.md.

**Change Impact** — Any change to `scripts/run_full_pipeline.py`'s printed output format must keep the exact `"Statement ID: <value>"` phrase intact, or this module's regex extraction silently breaks.

**Callers** — none (invoked once by M-009 at app startup)
**Calls** — M-011 (`claim_next_pending_job`, `update_job_status`, `get_vendor_name_for_statement`), M-018 (`scripts/run_full_pipeline.py`, via subprocess)
**Integration Points Used** — none directly (delegates all DB/pipeline work to what it calls)
