## G12 — Worker Simulation (Basic)
ID: M-048
Layer: infra
Source file: `test_worker_sim.py`

**Module** — Worker Simulation (Basic)
**ID** — M-048
**Layer** — infra
**Primary Responsibility** — Ad hoc dev script: runs the full pipeline via subprocess against one specific sample PDF, outside the actual worker thread, to sanity-check subprocess invocation mechanics in isolation.

**Inputs** — None (hardcoded PDF path: `sample_data/KSI_Noakers_053126.pdf`; hardcoded 60s timeout).

**Outputs** — Prints the first 30 lines of the subprocess's stdout.

**Public Interface** — None exported; script-only.

**Error Behaviour** — None — a bare `subprocess.run()` call; a `TimeoutExpired` at 60s would raise uncaught (notably shorter than the real worker's 1800s timeout — this script cannot exercise a genuinely slow extraction without hitting its own timeout first).

**Known Fragility** — The 60-second timeout is far shorter than production's 30-minute allowance (M-005) — this script can only validate the "happy path, fast case" and will falsely appear to fail (via `TimeoutExpired`) on any PDF whose real extraction genuinely takes longer than a minute, which is well within normal range for a multi-page statement.

**Change Impact** — None — isolated diagnostic tool, superseded in fidelity by M-049 (which reproduces the worker's exact path-construction logic).

**Callers** — none (developer-invoked)
**Calls** — M-021 (via `subprocess.run`)
**Integration Points Used** — none directly
