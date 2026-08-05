## C04 — matching CLI entry
ID: M-016
Layer: pipeline
Source file: notebooks/03_run_matching.py

**Module** — matching CLI entry
**ID** — M-016
**Layer** — pipeline
**Primary Responsibility** — CLI wrapper for the deterministic matching engine — runs matching for a given `statement_id` and prints a readable results/exceptions summary.

**Inputs** — `run(statement_id: str)`, CLI via `--statement-id` (required).

**Outputs** — Console output only (summary + exceptions list via `print_exceptions()`). The actual Gold-table writes happen inside `src.matching.engine.run_matching()` (M-036).

**Public Interface**
- `run(statement_id: str) -> dict`
- `print_exceptions(statement_id: str)` — reads `gold_exceptions` directly for display.

**Error Behaviour** — No try/except — `run_matching()` (M-036) raises `ValueError` if either side (statement or ERP) has zero Silver rows for the given `statement_id`; propagates uncaught, appropriate fail-fast for a script requiring both a prior intake and mock-ERP run.

**Known Fragility** — None specific — thin, correctly-scoped CLI wrapper.

**Change Impact** — Coupled to `run_matching()`'s exact return dict keys (`vendor_id`, `total_invoices`, `matched_count`, `match_percentage`, `exception_count`, `statement_total`, `erp_total`, `difference`, `overall_status`, `erp_version`).

**Callers** — none directly (invoked via CLI; M-018 calls `src.matching.engine.run_matching()` directly, not through this wrapper)
**Calls** — M-036 (`run_matching`), M-033 (`execute_query`, for `print_exceptions()`)
**Integration Points Used** — IP-008 (indirectly, via M-036 and its own `print_exceptions()` query)
