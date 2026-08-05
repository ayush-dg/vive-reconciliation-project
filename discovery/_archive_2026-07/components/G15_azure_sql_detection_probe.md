## G15 — Azure-SQL-detection probe
ID: M-042
Layer: infra
Source file: check_subprocess.py

**Module** — Azure-SQL-detection probe
**ID** — M-042
**Layer** — infra
**Primary Responsibility** — Meets the BCE-009 module-worthiness bar (spawns a real subprocess that exercises `connection.py`'s actual backend-detection function, not an assertion). Ad hoc dev diagnostic: confirms whether a fresh subprocess resolves `_using_azure_sql()` and `AZURE_SQL_SERVER` the same way as the invoking process.

**Inputs** — None (no CLI args).

**Outputs** — Prints the subprocess's stdout (`azure_sql: True/False`, `env: True/False`) and truncated stderr.

**Public Interface** — None (script-only).

**Error Behaviour** — None explicit — `subprocess.run()`'s own return captures stdout/stderr regardless of the child's exit code; this script doesn't check the return code itself, so a child-process crash would still print whatever partial output/stderr it produced without this script itself raising.

**Known Fragility** — Purpose-built to diagnose exactly one class of bug: a subprocess (like `web/worker.py`'s pipeline invocation) silently resolving a *different* backend than the parent process because `.env` wasn't loaded the same way — directly relevant to the real `load_dotenv(os.path.join(PROJECT_ROOT, ".env"))` explicit-path pattern used throughout `notebooks/01_document_intake.py` and `scripts/run_full_pipeline.py` specifically to prevent this class of bug (confirmed by cross-referencing those files' own comments, which describe this exact failure mode).

**Change Impact** — None — standalone diagnostic, not imported anywhere.

**Callers** — none (invoked directly, `python check_subprocess.py`)
**Calls** — M-033 (indirectly, via the spawned subprocess importing `_using_azure_sql`)
**Integration Points Used** — none directly (the subprocess it spawns would touch IP-008 only insofar as `_using_azure_sql()` itself just reads an env var, not the database)
