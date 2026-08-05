## G17 — worker simulation (path-exact)
ID: M-044
Layer: infra
Source file: test_worker_sim2.py

**Module** — worker simulation (path-exact)
**ID** — M-044
**Layer** — infra
**Primary Responsibility** — Meets the BCE-009 module-worthiness bar (real subprocess exercising the real pipeline, mirroring `web/worker.py`'s exact invocation shape). Ad hoc dev diagnostic: reproduces `web/worker.py`'s exact `pdf_path`/`relative_pdf_path` construction (including the spaced filename `sample_data/KSI Noakers 053126.pdf`) to reproduce a worker-specific path-handling bug.

**Inputs** — None (no CLI args; target PDF path and 600s timeout are hardcoded).

**Outputs** — Prints up to 40 lines of the subprocess's combined stdout+stderr.

**Public Interface** — None (script-only).

**Error Behaviour** — None explicit; `subprocess.run(..., timeout=600)` would raise `subprocess.TimeoutExpired` uncaught past 10 minutes — a more realistic window than G16's 60s, closer to `web/worker.py`'s own 1800s but still an order of magnitude shorter.

**Known Fragility** — This is the script responsible for creating the duplicate `sample_data/KSI Noakers 053126.pdf` file identified during Session A0/A (confirmed byte-identical to `KSI_Noakers_053126.pdf` via SHA-256) — its explicit purpose was reproducing a real path-construction discrepancy between how a script invokes the pipeline versus how `web/worker.py` does it, using the spaced filename specifically because that's what the upload router (`web/routers/upload.py`) preserves verbatim from a client's original filename.

**Change Impact** — None — standalone diagnostic, not imported anywhere. Its existence and hardcoded path are the direct explanation for the duplicate-file finding recorded in `discovery/components/A02_module_call_map.md`.

**Callers** — none (invoked directly, `python test_worker_sim2.py`)
**Calls** — M-018 (`scripts/run_full_pipeline.py`, via subprocess)
**Integration Points Used** — none directly
