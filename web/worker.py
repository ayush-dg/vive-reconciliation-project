"""
worker.py

Background job worker — polls the jobs table for PENDING rows and runs
them through the existing pipeline one at a time, via subprocess (never
touches pipeline internals directly — see web/routers/upload.py, which
uses the same subprocess pattern for a synchronous single-file upload).

Runs on a daemon thread started from web/app.py at application startup.
Must never crash: every exception is caught so one bad PDF can't take the
worker down and silently stop processing everything queued after it.
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
STATEMENT_ID_RE = re.compile(r"Statement ID:\s*(\S+)")

_worker_started = False
_start_lock = threading.Lock()


def _run_job(job: dict) -> None:
    from web import queries

    job_id = job["job_id"]
    pdf_path = job["pdf_path"]

    print(f"[worker] Starting job {job_id} ({job['pdf_filename']})")
    queries.update_job_status(
        job_id, status="PROCESSING", started_at=datetime.now(timezone.utc).isoformat()
    )

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


def _worker_loop() -> None:
    from web import queries

    while True:
        try:
            job = queries.get_next_pending_job()
            if job:
                _run_job(job)
        except Exception:
            traceback.print_exc()  # log and keep going — never let the loop die
        time.sleep(POLL_INTERVAL_SECONDS)


def start_worker() -> None:
    """Starts the background worker thread once per process. Safe to call
    more than once — only the first call actually starts the thread."""
    global _worker_started
    with _start_lock:
        if _worker_started:
            return
        _worker_started = True
    thread = threading.Thread(target=_worker_loop, name="vive-job-worker", daemon=True)
    thread.start()
    print(f"[worker] Background job worker started (polling every {POLL_INTERVAL_SECONDS}s)")
