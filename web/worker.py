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
import uuid
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PYTHON = os.path.join(
    PROJECT_ROOT, "venv",
    "Scripts" if os.name == "nt" else "bin",
    "python.exe" if os.name == "nt" else "python",
)
SAMPLE_DATA_DIR = os.path.join(PROJECT_ROOT, "sample_data")

POLL_INTERVAL_SECONDS = 30
DEFAULT_WORKER_POOL_SIZE = 3
STATEMENT_ID_RE = re.compile(r"Statement ID:\s*(\S+)")

# Dropzone auto-intake, polling variant -- see _dropzone_watcher_loop()'s
# docstring for why this exists alongside (not instead of)
# web/routers/intake_trigger.py's Event Grid webhook.
DROPZONE_POLL_INTERVAL_SECONDS = 30
DROPZONE_CONTAINER = "incoming-statements"
DROPZONE_CONNECTION_STRING_ENV_VAR = "AZURE_BLOB_DROPZONE_CONNECTION_STRING"

_worker_started = False
_start_lock = threading.Lock()
_shutdown_event = threading.Event()
_worker_threads = []
_dropzone_thread = None


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

        # Exit code 0 and a real-looking "Statement ID: ..." line are
        # necessary but not sufficient -- run_full_pipeline.py prints that
        # exact line (see its own PIPELINE STOPPED branch) even when
        # extraction produced zero usable invoice rows, then returns
        # normally (exit 0). Confirmed live 2026-08-23: 7 of 13 jobs this
        # regex-only check had marked COMPLETED actually had zero rows
        # anywhere in Bronze/Silver. Verify against real data before
        # trusting the text.
        silver_count = queries.get_silver_row_count(statement_id)
        if silver_count == 0:
            print(f"[worker] Job {job_id} FAILED (exit 0, but {statement_id} has zero Silver rows)")
            queries.update_job_status(
                job_id,
                status="FAILED",
                completed_at=completed_at,
                statement_id=statement_id,
                error_message=(
                    f"Extraction completed but produced 0 rows for statement_id {statement_id} "
                    f"-- see application logs for this job's real output.\n\n{output.strip()[-4000:]}"
                ),
            )
            return

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


def _intake_dropzone_blob(client, blob_name: str) -> None:
    """Downloads one dropzone blob into sample_data/ and queues a PENDING
    job for it -- same effect as a manual UI upload (web/routers/upload.py)
    or an Event Grid BlobCreated delivery (web/routers/intake_trigger.py's
    _intake_blob_created_event(), which this deliberately mirrors). Deletes
    the blob from the dropzone container on success, so the dropzone stays
    a transient inbox rather than something this loop has to re-list and
    re-skip forever -- see BlobStorageClient.delete_blob()'s docstring for
    what happens if that delete itself fails (never blocks intake either
    way, since the job is already queued by that point).

    Non-PDF blobs (already filtered out by list_pdf_blobs(), but checked
    again here for safety) and download failures are skipped without
    raising -- one bad blob must never stop the watcher from picking up
    everything else waiting in the dropzone."""
    filename = os.path.basename(blob_name)
    if not filename.lower().endswith(".pdf"):
        return

    from web import queries

    os.makedirs(SAMPLE_DATA_DIR, exist_ok=True)
    dest_path = os.path.join(SAMPLE_DATA_DIR, filename)

    if not client.download_blob_by_name(blob_name, dest_path):
        return

    job_id = str(uuid.uuid4())
    queries.create_job(job_id=job_id, pdf_filename=filename, pdf_path=dest_path, submitted_by="dropzone-watcher")
    print(f"[dropzone-watcher] Queued job {job_id} for {filename!r} from dropzone")
    client.delete_blob(blob_name)


def _dropzone_watcher_loop() -> None:
    """
    Polls the 'incoming-statements' container of the dropzone storage
    account (AZURE_BLOB_DROPZONE_CONNECTION_STRING) for newly-landed PDFs
    and queues each as a job -- a second, independent way to trigger the
    pipeline beyond the UI upload flow (web/routers/upload.py), alongside
    (not replacing) the existing Event Grid webhook
    (web/routers/intake_trigger.py's POST /api/intake-trigger).

    Why polling instead of relying solely on the existing Event Grid
    webhook: Event Grid needs a live, publicly-reachable HTTPS endpoint to
    deliver BlobCreated events to, and a shared secret + Event Grid system
    topic/subscription provisioned against the dropzone storage account --
    real infrastructure this session did not stand up (the only deployed
    endpoint, the viverecondemo-app App Service, is currently stopped, and
    starting/reconfiguring someone else's shared deployment was out of
    this task's scope to do unilaterally). This loop needs neither a
    public endpoint nor a webhook subscription -- only the same connection
    string the app already has -- so it works today, in this environment,
    without any further Azure provisioning. The webhook code is left in
    place, unmodified: whichever mechanism is provisioned later, both
    converge on the exact same queries.create_job() + jobs-table-worker
    pipeline, so nothing about this loop needs to change if Event Grid is
    added on top later.

    Silently does nothing (never raises, never logs an error loop) if
    AZURE_BLOB_DROPZONE_CONNECTION_STRING isn't configured -- same
    "unconfigured means inert, not broken" convention as
    BlobStorageClient's own upload/download methods.
    """
    from src.storage.blob_client import BlobStorageClient

    client = BlobStorageClient(
        container_name=DROPZONE_CONTAINER,
        connection_string_env_var=DROPZONE_CONNECTION_STRING_ENV_VAR,
    )
    if not client.connection_string:
        print(f"[dropzone-watcher] {DROPZONE_CONNECTION_STRING_ENV_VAR} not set -- watcher will not poll.")

    while not _shutdown_event.is_set():
        try:
            if client.connection_string:
                for blob_name in client.list_pdf_blobs():
                    _intake_dropzone_blob(client, blob_name)
        except Exception:
            traceback.print_exc()  # log and keep going — never let the loop die
        _shutdown_event.wait(DROPZONE_POLL_INTERVAL_SECONDS)
    print("[dropzone-watcher] stopped")


def start_worker() -> None:
    """Starts the background worker pool (_pool_size() threads, from
    VIVE_WORKER_POOL_SIZE, default 3) plus the dropzone watcher thread,
    once per process. Safe to call more than once — only the first call
    actually starts the threads."""
    global _worker_started, _dropzone_thread
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

    _dropzone_thread = threading.Thread(
        target=_dropzone_watcher_loop, name="vive-dropzone-watcher", daemon=True
    )
    _dropzone_thread.start()
    print(f"[worker] Dropzone watcher started (polling every {DROPZONE_POLL_INTERVAL_SECONDS}s)")


def stop_workers(timeout: float = None) -> None:
    """Signals every worker (including the dropzone watcher) to stop, then
    waits for each thread to exit. A worker mid-job finishes that job
    first — _shutdown_event is only checked between jobs, never used to
    interrupt a running subprocess — so this always returns after any
    in-flight pipeline runs complete (or after `timeout` per thread, if
    given). Safe to call even if the pool was never started (join() on an
    empty list, or on a None thread, is a no-op)."""
    _shutdown_event.set()
    for thread in _worker_threads:
        thread.join(timeout=timeout)
    if _dropzone_thread is not None:
        _dropzone_thread.join(timeout=timeout)
