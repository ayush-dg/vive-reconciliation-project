## G05 — AI-Call Concurrency Limiter
ID: M-041
Layer: infra
Source file: `src/ai/concurrency_limiter.py`

**Module** — AI-Call Concurrency Limiter
**ID** — M-041
**Layer** — infra
**Primary Responsibility** — Cross-process semaphore capping concurrent Claude Sonnet extraction calls at `VIVE_MAX_CONCURRENT_AI_CALLS` (default 2), using exclusive-create lock files on disk — necessary because each job runs in its own subprocess, so an in-process `threading.Semaphore` can't coordinate across them.

**Inputs** — `VIVE_MAX_CONCURRENT_AI_CALLS` env var; the calling process's PID (written into the lock file for diagnostic purposes, not read back by any code this session found).

**Outputs** — Lock files under `lakehouse/ai_call_slots/slot_N.lock`, created and removed as calls acquire/release a slot.

**Public Interface** — `ai_call_slot()` — a context manager; blocks (polling every 0.5s) until a slot is free, yields, then releases on exit including on exception.

**Error Behaviour** — The `finally` block's `os.remove(slot_path)` is itself wrapped in `except OSError: pass` — a slot file that's already gone (e.g. manually cleaned up mid-run) doesn't raise on release.

**Known Fragility**
- **A killed process (not a normal exception — the `finally` block only runs on normal Python-level exception unwinding, not on `SIGKILL`/OS-level termination) never releases its slot** — explicitly documented as a known, accepted limitation in this module's own docstring, same posture as the archived `RISK_REGISTER.md` R-010. Capacity is permanently reduced by one until the stale lock file is manually deleted.
- The busy-wait poll (`time.sleep(POLL_INTERVAL_SECONDS)`, 0.5s) means a worker waiting for a slot burns a thread doing nothing but sleeping and re-checking — acceptable at today's scale (2-slot default, 3-worker pool) but not a queue/notification mechanism that would scale gracefully to a much larger worker pool.
- Slot acquisition (`_try_acquire_slot()`) scans `slot_0` through `slot_{max_concurrent-1}` linearly every poll cycle — fine at `max_concurrent=2`, a real (if small) inefficiency if this constant were raised significantly.

**Change Impact** — Wraps only the real network call inside M-025's `_real_file_call()`/`_real_text_call()` — a cache hit or a test-injected transport never enters this context, so this module's behavior is invisible to anything except genuine live Claude Sonnet calls.

**Callers** — M-025 (`ai_call_slot()`)
**Calls** — none
**Integration Points Used** — none (local filesystem coordination only)
