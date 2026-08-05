## C03 — Mock ERP Generation Entry Point
ID: M-018
Layer: pipeline
Source file: `notebooks/02_generate_mock_erp.py`

**Module** — Mock ERP Generation Entry Point
**ID** — M-018
**Layer** — pipeline
**Primary Responsibility** — CLI entry point for the re-reconciliation workflow: regenerate the Mock ERP side for a given `statement_id` from `scenario_config.json`, without re-running AI extraction.

**Inputs** — `--statement-id` CLI argument.

**Outputs** — Stdout summary of counts (exact matches, missing, mismatches, duplicates, pending, renumbered); delegates the actual writes to M-035.

**Public Interface** — `run(statement_id: str) -> dict` — thin wrapper, not called by any other module (CLI-only, per RULE-05).

**Error Behaviour** — No error handling of its own; any exception from M-035 (e.g. `ValueError` on zero Silver rows) propagates uncaught.

**Known Fragility** — Deliberately CLI-only (RULE-05) — must never be wired into the dashboard even once one exists, per this module's own docstring and `INTAKE_SUMMARY.md`'s Known Architecture notes.

**Change Impact** — Isolated; not called by M-021 or any web-facing code — the orchestrator (M-021) calls M-035's functions directly rather than through this script.

**Callers** — none (developer-invoked CLI entry point)
**Calls** — M-035 (`generate_mock_erp`, `normalize_erp_to_silver`)
**Integration Points Used** — none directly
