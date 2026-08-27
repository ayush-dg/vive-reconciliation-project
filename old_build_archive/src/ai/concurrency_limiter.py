"""
concurrency_limiter.py

Cross-process semaphore limiting concurrent Claude Sonnet extraction calls
(see claude_sonnet_client.py's _real_file_call/_real_text_call). Each
vendor-statement job runs in its own subprocess (web/worker.py's worker
pool shells out to scripts/run_full_pipeline.py per job), so an in-process
threading.Semaphore can't coordinate across jobs claimed by different
workers -- this uses lock files on disk instead, which every subprocess
shares regardless of which worker thread spawned it.

Configurable via VIVE_MAX_CONCURRENT_AI_CALLS (default 2) -- Azure
Foundry's Claude Sonnet 4.6 deployment has a rate limit that a full worker
pool running unthrottled could exceed.

Known limitation, accepted rather than engineered around (same posture as
docs/RISK_REGISTER.md R-004's accepted stale-job gap): if a process holding
a slot is killed outright (not a normal exception, which the `finally`
below still cleans up after), that slot's lock file is never removed and
capacity is permanently reduced by one until it's manually deleted from
lakehouse/ai_call_slots/.
"""

import os
import time
from contextlib import contextmanager

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SLOT_DIR = os.path.join(PROJECT_ROOT, "lakehouse", "ai_call_slots")

DEFAULT_MAX_CONCURRENT = 2
POLL_INTERVAL_SECONDS = 0.5


def _max_concurrent() -> int:
    return int(os.environ.get("VIVE_MAX_CONCURRENT_AI_CALLS", DEFAULT_MAX_CONCURRENT))


def _try_acquire_slot(max_concurrent: int):
    """Attempts to atomically claim one of slot_0 .. slot_{max_concurrent-1}
    by exclusively creating its lock file (os.O_EXCL is atomic across
    processes on both POSIX and Windows). Returns the claimed path, or
    None if every slot is currently held."""
    os.makedirs(SLOT_DIR, exist_ok=True)
    for slot_id in range(max_concurrent):
        slot_path = os.path.join(SLOT_DIR, f"slot_{slot_id}.lock")
        try:
            fd = os.open(slot_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        os.write(fd, str(os.getpid()).encode("utf-8"))
        os.close(fd)
        return slot_path
    return None


@contextmanager
def ai_call_slot():
    """Blocks until a slot is free, then yields — releasing it on exit,
    including on exception. Wrap only the actual network call with this,
    not the whole job: a cache hit never enters this context, so it never
    waits on a slot for an AI call it isn't going to make."""
    max_concurrent = _max_concurrent()
    slot_path = None
    while slot_path is None:
        slot_path = _try_acquire_slot(max_concurrent)
        if slot_path is None:
            time.sleep(POLL_INTERVAL_SECONDS)
    try:
        yield
    finally:
        try:
            os.remove(slot_path)
        except OSError:
            pass
