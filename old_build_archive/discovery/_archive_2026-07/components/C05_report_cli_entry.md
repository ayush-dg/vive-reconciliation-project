## C05 — report CLI entry
ID: M-017
Layer: pipeline
Source file: notebooks/04_generate_report.py

**Module** — report CLI entry
**ID** — M-017
**Layer** — pipeline
**Primary Responsibility** — Generates and prints a complete reconciliation report for a statement_id, reading all Gold tables; optionally triggers AI exception explanations first via `--explain`.

**Inputs** — `generate_report(statement_id: str, run_explanations: bool = False, max_explanations: int = 10)`, CLI via `--statement-id` (required), `--explain` (flag), `--max-explanations` (default 10).

**Outputs** — Console-only structured report: statement summary, reconciliation results, exceptions (with AI explanations if present/requested), top-5 matched invoices by amount, AI audit log activity, next-steps guidance. No database writes of its own — delegates the one write path (AI explanations) to `ExplanationService` (M-029).

**Public Interface**
- `generate_report(statement_id, run_explanations=False, max_explanations=10)`

**Error Behaviour** — Explicit early-return guard: if no `gold_reconciliation_summary` row exists for `statement_id`, prints a clear message ("Run notebooks/03_run_matching.py first") and returns rather than raising or crashing on a `None`/index error downstream. No other explicit error handling — a failure inside `ExplanationService.explain_all_open_exceptions()` (M-029) would propagate uncaught if it ever raised (though M-029 is itself designed not to raise per-exception failures).

**Known Fragility** — **Docstring is stale, confirmed by direct code comparison**: line 11 reads "calls the active AI provider (Azure OpenAI gpt-5-mini) to add AI explanations" — the actual code (`from src.ai.explanation_service import ExplanationService`, `svc.explain_all_open_exceptions(statement_id)`) always uses `EXPLANATION_PROVIDER = "claude"` (hardcoded in M-029, independent of `provider_chain`). This is one of the six stale AI-provider-chain locations already catalogued in TOPOLOGY.md's STAGE-2-DIVERGENCE #2.

**Change Impact** — Depends on `gold_reconciliation_summary`, `gold_exceptions`, `gold_matched_invoices`, `document_intake_log`, and `ai_audit_log`'s exact column names for its printed fields — a schema rename in any of those tables breaks this report's output (likely `KeyError`, since it uses `s['field']` bracket access in several places rather than `.get()`).

**Callers** — M-018 (`scripts/run_full_pipeline.py`, via dynamic module load + `generate_report()` call, `run_explanations=args.explain`)
**Calls** — M-033 (`execute_query`), M-029 (`ExplanationService`)
**Integration Points Used** — IP-002 (Claude Haiku, indirectly via M-029), IP-008 (Lakehouse database)
