"""Per-step wall-clock timing lines for one pipeline run (one PDF).

Printed as "    Step timing: <step>=<seconds>s" -- the same 4-space-indented
status-line shape web/worker.py's FABRIC_STATUS_RE already surfaces from
scripts/run_full_pipeline.py's subprocess output, so every job's timings
land in the App Service log without any other plumbing.

Added 2026-09-28 to confirm where batch time goes once the Lakehouse
SQL-endpoint sync wait is out of the picture (BRONZE_TARGET=warehouse):
extraction/Bronze vs. queuing for fabric_pipeline_lock() vs. the dbt
Silver build vs. NetSuite matching.
"""
import contextlib
import os
import re
import time

_STEP_LINE = re.compile(r"^ {4}Step timing: (\w+)=([\d.]+)s\s*$", re.MULTILINE)


def parse_step_timings(output: str) -> list:
    """[(step, seconds), ...] from a run's captured output, in the order printed."""
    return [(name, float(seconds)) for name, seconds in _STEP_LINE.findall(output or "")]


TIMING_LOG_FLAG = "JOB_TIMING_LOG_ENABLED"
_COLUMNS = ("job_id", "statement_id", "pdf_filename", "step", "step_order", "seconds", "logged_at")


def timing_log_enabled() -> bool:
    """Whether each job's step timings are saved to the job_step_timing table. Off unless "true"."""
    return os.getenv(TIMING_LOG_FLAG, "").strip().lower() == "true"


def save_job_timings(job_id: str, pdf_filename, statement_id, steps: list):
    """Saves one row per step to job_step_timing (Azure SQL when deployed, SQLite locally) -- only while
    JOB_TIMING_LOG_ENABLED=true. Best-effort: returns the number of rows saved, and never raises, because a
    timing log must not be able to fail or slow a job."""
    if not timing_log_enabled() or not steps:
        return 0
    try:
        from datetime import datetime, timezone
        from src.lakehouse.connection import _run_with_retry
        logged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = [(job_id, statement_id, pdf_filename, name, order, float(seconds), logged_at)
                for order, (name, seconds) in enumerate(steps, start=1)]
        sql = f"INSERT INTO job_step_timing ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))})"

        def _run(conn):
            cursor = conn.cursor()
            cursor.executemany(sql, rows)
            conn.commit()

        _run_with_retry(_run)
        return len(rows)
    except Exception as exc:
        print(f"[timing] could not save step timings: {exc}", flush=True)
        return 0


def record_step(name: str, seconds: float) -> None:
    print(f"    Step timing: {name}={seconds:.1f}s", flush=True)


@contextlib.contextmanager
def timed_step(name: str):
    start = time.monotonic()
    try:
        yield
    finally:
        record_step(name, time.monotonic() - start)
