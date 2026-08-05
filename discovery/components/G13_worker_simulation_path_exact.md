## G13 — Worker Simulation (Exact Path Replication)
ID: M-049
Layer: infra
Source file: `test_worker_sim2.py`

**Module** — Worker Simulation (Exact Path Replication)
**ID** — M-049
**Layer** — infra
**Primary Responsibility** — Ad hoc dev script: reproduces `web/worker.py`'s (M-005) exact `pdf_path`/`relative_pdf_path` construction (including the literal space in the test filename, `"KSI Noakers 053126.pdf"`) to reproduce a worker-specific path-handling bug in isolation, outside the actual worker thread.

**Inputs** — None (hardcoded PDF path and 600s timeout).

**Outputs** — Prints the first 40 lines of combined stdout+stderr.

**Public Interface** — None exported; script-only.

**Error Behaviour** — None — a bare `subprocess.run()` call with a 600s (10 min) timeout, closer to but still shorter than production's 1800s allowance.

**Known Fragility** — Deliberately depends on a specific sample file with a literal space in its name still existing at that exact path (`sample_data/KSI Noakers 053126.pdf`) — the archived `A00_codebase_map.md` flagged this as likely a duplicate of `KSI_Noakers_053126.pdf` (identical byte size); if that file were ever cleaned up as a "duplicate," this script would silently stop testing what it was written to test (a space-containing filename path through `os.path.relpath()`), failing instead on file-not-found rather than the original bug it was written to reproduce.

**Change Impact** — None — isolated diagnostic tool.

**Callers** — none (developer-invoked)
**Calls** — M-021 (via `subprocess.run`)
**Integration Points Used** — none directly
