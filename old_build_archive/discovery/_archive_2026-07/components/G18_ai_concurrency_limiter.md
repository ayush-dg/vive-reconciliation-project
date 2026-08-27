## G18 — AI-call concurrency limiter
ID: M-047
Layer: infra
Source file: src/ai/concurrency_limiter.py
Added: 2026-07-25 scoped BCE refresh (module built 2026-07-24, Step 5, alongside the worker pool)

**Module** — AI-call concurrency limiter
**ID** — M-047
**Layer** — infra
**Primary Responsibility** — Cross-process semaphore capping the number of concurrent Claude Sonnet extraction calls, system-wide, regardless of how many worker-pool jobs are running at once.

**Inputs** — `ai_call_slot()` — a context manager, no arguments; reads `VIVE_MAX_CONCURRENT_AI_CALLS` (default 2) at call time via `_max_concurrent()`.

**Outputs** — Blocks (polling every `POLL_INTERVAL_SECONDS = 0.5`) until a slot is free, then yields; releases the slot on exit, including on exception. No return value — this is purely a blocking gate around the caller's own network call.

**Public Interface**
- `ai_call_slot()` — the only public entry point, a `@contextmanager`.
- `_try_acquire_slot(max_concurrent)` (private) — one atomic `os.O_CREAT | os.O_EXCL` attempt per configured slot.
- `_max_concurrent()` (private) — reads `VIVE_MAX_CONCURRENT_AI_CALLS`.

**Error Behaviour** — The `finally` block inside `ai_call_slot()` always attempts to remove the slot's lock file on the way out, including when the wrapped call raises — confirmed by source, matching the module's own docstring claim. `os.remove()`'s own `OSError` (e.g. the file was already gone) is itself caught and ignored, so releasing a slot can never itself raise. There is deliberately no timeout on the acquire loop — a caller will wait indefinitely for a free slot rather than fail fast; at current `VIVE_WORKER_POOL_SIZE`/`VIVE_MAX_CONCURRENT_AI_CALLS` defaults (3 and 2) this means at most one worker thread's job is ever waiting on a slot at a time, not an unbounded pile-up.

**Known Fragility**
- **A killed process leaks its slot permanently — this is the module's one self-documented, accepted limitation, not a bug found by this review.** If a process holding a slot is killed outright (OS-level kill, OOM kill, forced container restart — anything that skips the `finally` block, as opposed to a normal Python exception, which the `finally` still handles), that slot's lock file is never removed. Capacity is silently and permanently reduced by one until someone manually deletes the stale file from `lakehouse/ai_call_slots/`. No liveness check exists — each lock file stores the holding PID but nothing else ever reads it back to verify the process is still alive. See `discovery/RISK_REGISTER.md` R-010 for the risk writeup and a lightweight PID-liveness-check remediation sketch (not built, since no incident has yet demonstrated the need — consistent with IC-9's general posture on speculative hardening).
- **The 0.5s poll interval means a freed slot isn't necessarily claimed instantly** — under sustained contention (more concurrent extraction attempts than `VIVE_MAX_CONCURRENT_AI_CALLS`), a waiting caller could sit idle for up to ~0.5s after a slot actually frees before its next poll notices. Not a correctness issue (the cap itself is never exceeded), only a minor throughput/latency consideration at the margin.
- **This mechanism exists specifically because job isolation is process-level, not thread-level.** `web/worker.py`'s pool shells out to `scripts/run_full_pipeline.py` as a subprocess per job (see M-013), so an in-process `threading.Semaphore` inside the worker pool's own Python process could not coordinate the actual Claude Sonnet calls, which happen inside separate subprocesses. The disk-based lock-file approach is a deliberate, correct workaround for that architecture, not an accidental overcomplication.

**Change Impact** — Any change to `web/worker.py`'s subprocess-per-job architecture (M-013) — e.g. a future move to in-process job execution — would make this cross-process mechanism unnecessary and a simpler `threading.Semaphore` would become viable instead; conversely, this module must not be replaced with an in-process primitive while jobs remain subprocess-isolated.

**Callers** — M-023 (`src/ai/claude_sonnet_client.py`, wraps only the real network call — a cache hit never acquires a slot)
**Calls** — none (pure filesystem operations, no DB/network access of its own)
**Integration Points Used** — none directly (indirectly gates IP-001, Claude Sonnet 4.6, via its one caller)
