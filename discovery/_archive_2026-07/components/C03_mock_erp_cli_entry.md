## C03 — mock ERP CLI entry
ID: M-015
Layer: pipeline
Source file: notebooks/02_generate_mock_erp.py

**Module** — mock ERP CLI entry
**ID** — M-015
**Layer** — pipeline
**Primary Responsibility** — CLI wrapper for the mock ERP generator (RULE-05 CLI-only boundary) — generates ERP Bronze data from Silver VENDOR_STATEMENT rows, then normalizes it to Silver INTERNAL_ERP.

**Inputs** — `run(statement_id: str)`, CLI via `--statement-id` (required).

**Outputs** — Console progress/summary output only (the actual DB writes happen inside `src.mock_erp.generator`, M-037). Returns `counts` dict from `generate_mock_erp()`.

**Public Interface**
- `run(statement_id: str) -> dict`

**Error Behaviour** — No try/except of its own — `generate_mock_erp()` (M-037) raises `ValueError` if no Silver VENDOR_STATEMENT rows exist for the given `statement_id`; this module lets that propagate uncaught, printing a traceback to the CLI user, which is reasonable fail-fast behavior for a script requiring a valid prior intake run.

**Known Fragility** — None specific — a thin, correctly-scoped CLI wrapper around M-037's actual logic.

**Change Impact** — Coupled to `generate_mock_erp()`/`normalize_erp_to_silver()`'s exact return dict keys (`total_source`, `erp_rows_written`, `erp_version`, `exact_match`, `missing`, `amount_mismatch`, `duplicate`, `pending`) for its printed summary — a key rename in M-037 would break this script's output (likely a `KeyError`, not silent).

**Callers** — none directly (invoked via CLI, or dynamically loaded and called by M-018's `run_full_pipeline.py` — note: M-018 actually calls `src.mock_erp.generator`'s functions directly, not this CLI wrapper, per the A02 call trace — this module itself has no confirmed caller in the traced call graph beyond direct CLI invocation)
**Calls** — M-037 (`generate_mock_erp`, `normalize_erp_to_silver`)
**Integration Points Used** — IP-008 (indirectly, via M-037)
