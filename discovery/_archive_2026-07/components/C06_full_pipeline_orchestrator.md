## C06 — full pipeline orchestrator
ID: M-018
Layer: pipeline
Source file: scripts/run_full_pipeline.py

**Module** — full pipeline orchestrator
**ID** — M-018
**Layer** — pipeline
**Primary Responsibility** — Runs the complete reconciliation pipeline for one PDF in a single command: intake → mock ERP → matching → report. This is the script `web/worker.py` invokes as a subprocess for every queued job.

**Inputs** — `main()`, CLI via `--pdf` (required), `--statement-id` (optional), `--period` (optional), `--explain` (flag), `--max-explanations` (default 5).

**Outputs** — Console output only, aggregating all four phases' own prints (each phase's actual writes happen in the modules it calls). Prints the literal `Statement ID: {statement_id}` line M-013's worker regex-extracts to determine the outcome.

**Public Interface**
- `main()`
- `load_notebook(name, relative_path)` — loads a `notebooks/*.py` script as an importable module via `importlib.util`, since those scripts "were never meant to be package members."

**Error Behaviour**
- **Explicit early-stop guard**: if `intake_result.get("bronze_count", 0) == 0`, prints "PIPELINE STOPPED — no invoices extracted" and returns *before* attempting mock ERP generation (M-037) or matching (M-036) — both of which would otherwise raise `ValueError` on empty Silver data. This is a deliberate, graceful degradation, not an oversight.
- **No try/except around any of the four phase calls** — a genuine exception in intake, mock ERP, matching, or report generation propagates uncaught and unhandled all the way up to whatever invoked this script — for the worker (M-013), that means a nonzero exit code, which correctly marks the job FAILED.
- **Explicit UTF-8 reconfiguration for stdout/stderr on Windows** (`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`) — addresses a real, previously-encountered class of bug (cp1252 console encoding crashing on AI-extracted non-ASCII text), confirmed by the same pattern appearing independently in `notebooks/02/03/04`.

**Known Fragility** — **This script's printed `"Statement ID: {statement_id}"` line is a load-bearing string contract with `web/worker.py`'s regex extraction (M-013)** — any reformatting of this print statement silently breaks the worker's ability to record which statement a completed job produced, without any test or type system catching it. This is the single most fragile point in the whole web-upload-to-completion chain, confirmed by tracing both sides of the contract.
- Loads `.env` via an explicit absolute path (matching `web/app.py`'s pattern) specifically because this script is itself sometimes `exec`'d via `importlib.util.spec_from_file_location` from within another process (worker → subprocess → this script → dynamically-loaded notebook modules) — a bare `load_dotenv()` would be ambiguous across that many layers of invocation, confirmed by the code's own comment and by tracing the actual call chain.

**Change Impact** — Any change to the phase ordering or to the four called functions' signatures (`run_intake`, `generate_mock_erp`/`normalize_erp_to_silver`, `run_matching`, `generate_report`) must be reflected here, since this is the single top-level orchestration point for the entire pipeline.

**Callers** — M-013 (`web/worker.py`, via subprocess), M-043, M-044 (test scripts, via subprocess)
**Calls** — M-014 (`run_intake`, via `load_notebook`), M-037 (`generate_mock_erp`, `normalize_erp_to_silver`, direct import), M-036 (`run_matching`, direct import), M-017 (`generate_report`, via `load_notebook`)
**Integration Points Used** — IP-001 through IP-009 (transitively, everything the four phases touch)
