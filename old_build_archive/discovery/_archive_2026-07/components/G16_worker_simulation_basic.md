## G16 — worker simulation (basic)
ID: M-043
Layer: infra
Source file: test_worker_sim.py

**Module** — worker simulation (basic)
**ID** — M-043
**Layer** — infra
**Primary Responsibility** — Meets the BCE-009 module-worthiness bar (spawns a real subprocess running the actual full pipeline against a real sample PDF, not an assertion against a modeled module). Ad hoc dev diagnostic: runs `scripts/run_full_pipeline.py` via subprocess against `sample_data/KSI_Noakers_053126.pdf` and prints the first 30 lines of output.

**Inputs** — None (no CLI args; target PDF and timeout (60s) are hardcoded).

**Outputs** — Prints up to 30 lines of the subprocess's combined stdout.

**Public Interface** — None (script-only).

**Error Behaviour** — None explicit — `subprocess.run(..., timeout=60)` would raise `subprocess.TimeoutExpired` uncaught if the pipeline didn't finish in 60s, which is a tight window for a real AI extraction call (compare to `web/worker.py`'s own 1800s/30-minute timeout for the same underlying script) — this script is only useful for a fast (likely cache-hit) run, not a fresh extraction.

**Known Fragility** — The 60-second timeout is almost certainly too short for a fresh (non-cache-hit) extraction call to any of the real AI providers, several of which are documented elsewhere in this system as taking 65-245+ seconds per document (`gemini_client.py` module docstring) — this script would reliably fail with a timeout on a true cold run against `KSI_Noakers_053126.pdf` unless that document's hash is already cached.

**Change Impact** — None — standalone diagnostic, not imported anywhere. Superseded in purpose by G17 (`test_worker_sim2.py`), which more precisely mimics the real worker's path construction.

**Callers** — none (invoked directly, `python test_worker_sim.py`)
**Calls** — M-018 (`scripts/run_full_pipeline.py`, via subprocess)
**Integration Points Used** — none directly (exercises whatever the invoked pipeline run touches)
