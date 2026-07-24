"""
worker.py

Background job worker pool — a configurable number of threads (default 3,
see VIVE_WORKER_POOL_SIZE / _pool_size()) each independently poll the jobs
table for PENDING rows and run them through the existing pipeline via
subprocess (never touches pipeline internals directly — see
web/routers/upload.py, which uses the same subprocess pattern for a
synchronous single-file upload).

Started from web/app.py's lifespan at application startup, stopped from
the same lifespan's shutdown phase (see stop_workers()). Must never
crash: every exception is caught so one bad PDF can't take a worker down
and silently stop it from processing everything queued after it.

Job claiming (queries.claim_next_pending_job) is atomic and, as of
2026-07-24, scoped to pdf_filename rather than the whole table — see that
function's docstring and docs/INVARIANTS.md's amended INV-05 entry. That
change is what makes a pool of more than one worker here actually useful:
previously, only one job could be PROCESSING system-wide, so extra worker
threads would just poll and find nothing claimable. Two jobs for the
SAME PDF still can't run concurrently (that race — both missing the
other's extraction_cache write and re-running the full AI extraction — is
still prevented), but different statements now process in parallel, up
to VIVE_WORKER_POOL_SIZE at once and VIVE_MAX_CONCURRENT_AI_CALLS
concurrent Claude Sonnet calls (see src/ai/concurrency_limiter.py).
"""

import os
import re
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PYTHON = os.path.join(PROJECT_ROOT, "venv", "Scripts", "python.exe")

POLL_INTERVAL_SECONDS = 30
DEFAULT_WORKER_POOL_SIZE = 3
STATEMENT_ID_RE = re.compile(r"Statement ID:\s*(\S+)")

_worker_started = False
_start_lock = threading.Lock()
_shutdown_event = threading.Event()
_worker_threads = []


def _pool_size() -> int:
    return int(os.environ.get("VIVE_WORKER_POOL_SIZE", DEFAULT_WORKER_POOL_SIZE))


def _run_job(job: dict) -> None:
    from web import queries

    job_id = job["job_id"]
    pdf_path = job["pdf_path"]

    print(f"[worker] Starting job {job_id} ({job['pdf_filename']})")

    python_exe = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable
    relative_pdf_path = os.path.relpath(pdf_path, PROJECT_ROOT)

    try:
        result = subprocess.run(
            [python_exe, os.path.join("scripts", "run_full_pipeline.py"), "--pdf", relative_pdf_path],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,  # 30 min safety cap so one stuck PDF can't wedge the worker forever
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        match = STATEMENT_ID_RE.search(output)
        completed_at = datetime.now(timezone.utc).isoformat()

        if result.returncode != 0 or not match:
            print(f"[worker] Job {job_id} FAILED (exit {result.returncode})")
            queries.update_job_status(
                job_id,
                status="FAILED",
                completed_at=completed_at,
                error_message=output.strip()[-4000:] or "Pipeline exited with no output.",
            )
            return

        statement_id = match.group(1)
        vendor_name = queries.get_vendor_name_for_statement(statement_id)
        print(f"[worker] Job {job_id} COMPLETED — {statement_id} ({vendor_name})")
        queries.update_job_status(
            job_id,
            status="COMPLETED",
            completed_at=completed_at,
            statement_id=statement_id,
            vendor_name=vendor_name,
        )
    except Exception as e:
        print(f"[worker] Job {job_id} FAILED with worker error: {e}")
        try:
            queries.update_job_status(
                job_id,
                status="FAILED",
                completed_at=datetime.now(timezone.utc).isoformat(),
                error_message=f"Worker error: {e}",
            )
        except Exception:
            pass  # even the failure write must never take the worker loop down


def _worker_loop(worker_name: str) -> None:
    from web import queries

    while not _shutdown_event.is_set():
        try:
            job = queries.claim_next_pending_job()
            if job:
                _run_job(job)
        except Exception:
            traceback.print_exc()  # log and keep going — never let the loop die
        # Event.wait() (rather than time.sleep()) so a shutdown request wakes
        # this loop immediately instead of after the full poll interval —
        # checked only here, between jobs, so a job already in flight always
        # runs to completion before the loop re-checks _shutdown_event.
        _shutdown_event.wait(POLL_INTERVAL_SECONDS)
    print(f"[worker] {worker_name} stopped")


def start_worker() -> None:
    """Starts the background worker pool (_pool_size() threads, from
    VIVE_WORKER_POOL_SIZE, default 3) once per process. Safe to call more
    than once — only the first call actually starts the threads."""
    global _worker_started
    with _start_lock:
        if _worker_started:
            return
        _worker_started = True

    pool_size = _pool_size()
    for i in range(pool_size):
        worker_name = f"vive-job-worker-{i}"
        thread = threading.Thread(target=_worker_loop, args=(worker_name,), name=worker_name, daemon=True)
        thread.start()
        _worker_threads.append(thread)
    print(f"[worker] Background job worker pool started "
          f"({pool_size} workers, polling every {POLL_INTERVAL_SECONDS}s)")


def stop_workers(timeout: float = None) -> None:
    """Signals every worker to stop, then waits for each thread to exit.
    A worker mid-job finishes that job first — _shutdown_event is only
    checked between jobs, never used to interrupt a running subprocess —
    so this always returns after any in-flight pipeline runs complete (or
    after `timeout` per thread, if given). Safe to call even if the pool
    was never started (join() on an empty list is a no-op)."""
    _shutdown_event.set()
    for thread in _worker_threads:
        thread.join(timeout=timeout)
