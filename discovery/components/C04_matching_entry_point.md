## C04 — Matching Engine Entry Point
ID: M-019
Layer: pipeline
Source file: `notebooks/03_run_matching.py`

**Module** — Matching Engine Entry Point
**ID** — M-019
**Layer** — pipeline
**Primary Responsibility** — CLI entry point for the deterministic matching engine; prints a formatted reconciliation summary and, if exceptions exist, the re-run instructions.

**Inputs** — `--statement-id` CLI argument.

**Outputs** — Stdout report; delegates all writes to M-034.

**Public Interface** — `run(statement_id: str) -> dict`, `print_exceptions(statement_id: str)` — neither called by any other module; a standalone CLI script, not imported elsewhere (M-021 calls M-034 directly instead).

**Error Behaviour** — No error handling of its own; `run_matching()`'s `ValueError` on missing Silver data propagates uncaught.

**Known Fragility** — None beyond what M-034 already carries.

**Change Impact** — Isolated.

**Callers** — none (developer-invoked CLI entry point)
**Calls** — M-034 (`run_matching`), M-037 (`execute_query`, for `print_exceptions()`)
**Integration Points Used** — IP-008 (via M-037)
