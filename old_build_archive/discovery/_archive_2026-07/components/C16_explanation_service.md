## C16 — explanation service
ID: M-029
Layer: pipeline
Source file: src/ai/explanation_service.py

**Module** — explanation service
**ID** — M-029
**Layer** — pipeline
**Primary Responsibility** — Generates AI-powered, business-friendly narrative explanations for `gold_exceptions` rows. Deliberately decoupled from the document extraction chain — hardcodes `"claude"` (Haiku 4.5, M-022), independent of `active_provider.json`'s `provider_chain`. Confirmed correct behavior — this is the one instance where "hardcodes a provider independent of the chain" is accurate and intentional, not stale.

**Inputs** — `ExplanationService(max_per_run=10)`; `explain_all_open_exceptions(statement_id: str) -> dict`.

**Outputs** — Updates `gold_exceptions.ai_explanation`, `ai_suggested_resolution`, `ai_confidence_score`, `ai_provider` for each exception explained. Never changes `match_status`, `exception_reason`, or any financial figure — confirmed by source, matching the module's own stated invariant.

**Public Interface**
- `class ExplanationService`: `__init__(max_per_run=10)`, `explain_all_open_exceptions(statement_id) -> dict` (`{"explained": n, "skipped": n, "failed": n}`), `_explain_one(exception_row, statement_id) -> bool` (private), `_write_explanation(...)` (private)
- `EXPLANATION_PROVIDER = "claude"` (module-level constant)

**Error Behaviour** — Only processes `gold_exceptions` rows with `exception_status = 'OPEN' AND ai_explanation IS NULL` — already-explained or resolved exceptions are never re-processed. `_explain_one()` catches a client-load failure (`get_ai_client(EXPLANATION_PROVIDER)` raising) and returns `False` for that row rather than aborting the whole batch; a per-exception AI call failure similarly just marks that one row `failed` and continues to the next.

**Known Fragility** — **`max_output_tokens=1024` is deliberately capped well below the client's own 65536 default** — the code comment explains a non-streaming call above ~16K tokens trips the Anthropic SDK's own "streaming is required" guard, and this is a few sentences of JSON, not a document extraction — confirmed a deliberate, reasoned constraint, not an arbitrary number.

**Change Impact** — If `EXPLANATION_PROVIDER` were ever changed, note that `ClaudeClient`'s plain `generate()` (not `generate_with_file()`) is what's actually exercised here — a provider swap must support text-only completion, ruling out e.g. `DocumentIntelligenceClient` (M-024), which only supports `generate_with_file()`.

**Callers** — M-017 (`notebooks/04_generate_report.py`, only under `--explain`)
**Calls** — M-031 (`client_factory.get_ai_client("claude")`), M-032 (`log_ai_call`), M-033 (`execute_sql`, `execute_query`)
**Integration Points Used** — IP-002 (Claude Haiku 4.5)
