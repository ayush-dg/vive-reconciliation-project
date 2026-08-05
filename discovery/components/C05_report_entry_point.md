## C05 — Report Generation Entry Point
ID: M-020
Layer: pipeline
Source file: `notebooks/04_generate_report.py`

**Module** — Report Generation Entry Point
**ID** — M-020
**Layer** — pipeline
**Primary Responsibility** — Reads all Gold tables for a `statement_id` and prints a structured, human-readable reconciliation report; optionally generates AI explanations for open exceptions first.

**Inputs** — `--statement-id`, `--explain`, `--max-explanations` CLI args (or direct call params).

**Outputs** — Stdout report; if `--explain`, also triggers M-033's writes to `gold_exceptions.ai_explanation`/etc.

**Public Interface** — `generate_report(statement_id, run_explanations=False, max_explanations=10)` — called by M-021.

**Error Behaviour** — If no `gold_reconciliation_summary` row exists for the statement, prints a message and returns cleanly (no exception) — the only report function with an explicit "nothing to report" early exit.

**Known Fragility** — Reads `document_intake_log` via M-037's Fabric path (`execute_query_fabric`) with no trailing `LIMIT`, relying on `write_intake_log()`'s own DELETE-before-INSERT to guarantee at most one row — if that guarantee is ever violated (e.g. a future write site inserts without deleting first), this silently picks whichever row the backend happens to return first, not necessarily the most recent.

**Change Impact** — Called by M-021 as part of every full pipeline run — a failure here (e.g. an unhandled exception in the explanation service) would abort Phase 4 of the orchestrator, though Phases 1–3's writes (Bronze/Silver/Gold) are already durable by that point.

**Callers** — M-021 (`generate_report`, via dynamic module load)
**Calls** — M-033 (`ExplanationService().explain_all_open_exceptions()`), M-037 (`execute_query`/`execute_query_fabric`)
**Integration Points Used** — IP-008, IP-011 (both via M-037, transitive)
