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
import time


def record_step(name: str, seconds: float) -> None:
    print(f"    Step timing: {name}={seconds:.1f}s", flush=True)


@contextlib.contextmanager
def timed_step(name: str):
    start = time.monotonic()
    try:
        yield
    finally:
        record_step(name, time.monotonic() - start)
