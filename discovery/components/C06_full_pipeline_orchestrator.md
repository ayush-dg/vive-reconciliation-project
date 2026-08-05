## C06 — Full Pipeline Orchestrator
ID: M-021
Layer: pipeline
Source file: `scripts/run_full_pipeline.py`

**Module** — Full Pipeline Orchestrator
**ID** — M-021
**Layer** — pipeline
**Primary Responsibility** — Single-command runner chaining all 4 pipeline phases (intake → mock ERP → matching → report) for one PDF; the exact script `web/worker.py` (M-005) shells out to per job.

**Inputs** — `--pdf`, `--statement-id`, `--period`, `--explain`, `--max-explanations` CLI args.

**Outputs** — Delegates all data writes to M-017/M-035/M-034/M-020; stdout progress markers, including the `"Statement ID: ..."` line M-005's regex (`STATEMENT_ID_RE`) depends on to detect success.

**Public Interface** — `main()`, `load_notebook(name, relative_path)` — not called by any other module as a library; invoked only as a subprocess (by M-005, M-048, M-049) or directly from the CLI.

**Error Behaviour**
- Catches `CorruptedPDFError` specifically around Phase 1, printing a clean `"PIPELINE FAILED"` block and `sys.exit(1)` — this is the exit code M-005's worker checks for a FAILED job.
- If Phase 1 completes with `bronze_count == 0`, prints `"PIPELINE STOPPED — no invoices extracted"` and returns cleanly (exit 0, not a failure) — a genuinely empty extraction is not treated as a pipeline error.
- No error handling around Phases 2–4 — an exception there propagates as an uncaught traceback and non-zero exit, which M-005 also correctly interprets as FAILED (any non-zero exit, not just the specific `CorruptedPDFError` case).

**Known Fragility**
- **`web/worker.py`'s success/failure detection depends entirely on this script's stdout containing the literal string `"Statement ID: "` and on the process exit code** — any change to this print statement's exact text, or to how `run_intake()`'s result dict is surfaced, silently breaks the worker's ability to record a `statement_id` on a completed job (it would still mark COMPLETED via exit code 0, but `STATEMENT_ID_RE` would fail to match, leaving the job's `statement_id` unset).
- `load_notebook()`'s `importlib.util.spec_from_file_location()` pattern loads `01_document_intake.py` and `04_generate_report.py` as ad hoc modules rather than package imports — a deliberate choice (they're numbered CLI scripts, not package members) but means neither module's own `if __name__ == "__main__":` block guard prevents re-execution of module-level code if either script ever adds side effects outside function definitions.

**Change Impact** — This is the sole subprocess boundary the entire worker pool (M-005) depends on — any behavioral change here has system-wide effect on every queued job, not just direct callers.

**Callers** — M-005 (via subprocess), M-048, M-049 (dev scripts, via subprocess)
**Calls** — M-017 (`run_intake`, via `load_notebook`), M-035 (`generate_mock_erp`, `normalize_erp_to_silver`), M-034 (`run_matching`), M-020 (`generate_report`, via `load_notebook`)
**Integration Points Used** — none directly (all transitive through the four phases)
