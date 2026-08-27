## C18 — Exception Explanation Service
ID: M-033
Layer: pipeline
Source file: `src/ai/explanation_service.py`

**Module** — Exception Explanation Service
**ID** — M-033
**Layer** — pipeline
**Primary Responsibility** — Generates plain-language explanations for open `gold_exceptions` rows via Claude Haiku (M-026), hardcoded independently of `active_provider.json`'s extraction chain. Never alters match/exception decisions or financial figures — narrative only.

**Inputs** — `statement_id`; `max_per_run` (constructor arg, default 10) caps exceptions explained per run.

**Outputs** — Updates `gold_exceptions.ai_explanation`/`ai_suggested_resolution`/`ai_confidence_score`/`ai_provider` for each explained row.

**Public Interface** — `ExplanationService(max_per_run=10)`, `.explain_all_open_exceptions(statement_id) -> dict` (`{"explained": N, "skipped": N, "failed": N}`).

**Error Behaviour** — `_explain_one()` never raises — a missing provider or a failed API call is caught, printed, and counted as `failed`; the loop continues to the next exception. `log_ai_call()` failures are silently swallowed, same pattern as M-024.

**Known Fragility** — `EXPLANATION_PROVIDER = "claude"` is hardcoded at module level, independent of `active_provider.json` — this is a deliberate design choice (documented in the module docstring: explanation is a small text-only task, decoupled from the document-extraction provider's speed/accuracy tradeoffs), not an oversight, but a future engineer wanting to change the explanation provider must edit this constant directly, not the config file that governs extraction.

**Change Impact** — Read-only summary layer, entirely independent of extraction/matching — a failure here never blocks or corrupts pipeline data, only leaves `ai_explanation` fields unpopulated.

**Callers** — M-020 (`ExplanationService().explain_all_open_exceptions()`, only when `--explain` is passed)
**Calls** — M-023 (`get_ai_client("claude")`), M-040 (`log_ai_call`), M-037 (`execute_sql`/`execute_query`)
**Integration Points Used** — IP-002 (Claude Haiku 4.5, via M-026, transitive), IP-008 (via M-037)
