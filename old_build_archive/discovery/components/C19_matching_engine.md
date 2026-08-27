## C19 — Matching Engine
ID: M-034
Layer: pipeline
Source file: `src/matching/engine.py`

**Module** — Matching Engine
**ID** — M-034
**Layer** — pipeline
**Primary Responsibility** — 100% deterministic, zero-AI matching between Silver VENDOR_STATEMENT and INTERNAL_ERP rows for a statement_id; writes all three Gold tables in one call.

**Inputs** — `statement_id`; `config/matching/matching_rules.json` (tolerance thresholds).

**Outputs** — Rows in `gold_matched_invoices`, `gold_exceptions`, `gold_reconciliation_summary` — full DELETE-then-rewrite per `statement_id` on every call (idempotent re-run), except `EXTRACTION_INCOMPLETE` exceptions, which are explicitly exempted from the DELETE since matching never recreates them.

**Public Interface**
- `run_matching(statement_id, rules_path=...) -> dict` — the primary entry point.
- `classify_match(stmt_invoice, erp_candidates, tolerance_pct, tolerance_abs) -> dict` — pure function, called directly by tests (M-050 and presumably `tests/test_matching_engine.py`, not re-read this session).
- `amounts_match(...)`, `score_match_confidence(...)`, `score_overall_status(exception_count) -> str`, `score_exception_confidence(exception_reason) -> float`, `load_matching_rules(...)`.

**Error Behaviour** — `run_matching()` raises `ValueError` if either side (VENDOR_STATEMENT or INTERNAL_ERP) has zero Silver rows for the statement_id — a hard stop, not a degraded result, since matching against an empty set would be meaningless.

**Known Fragility**
- **Confirmed exactly 2 match levels, not 3** — `MATCH_LEVEL_TO_TYPE = {1: "INVOICE", 2: "RO"}`. A third "fuzzy prefix" level existed once and was deliberately removed (RULE-11) after it silently cross-matched unrelated invoices sharing a common prefix and coincidentally equal amounts — the module's own comments preserve this history explicitly so it isn't reintroduced.
- `MATCH_CONFIDENCE` includes `PO`/`FUZZY`/`("INVOICE","MISMATCH")` entries `classify_match()` can never actually produce today (no PO-based matching level exists; an invoice-number match with mismatched amount always becomes an "Amount Mismatch" exception, never a matched row at a lower confidence) — included deliberately so the table doesn't need restructuring the moment one of those paths is added, but a reader could reasonably assume all listed match types are currently reachable.
- `score_overall_status()` is the single shared tiering function this module and `web/queries.py`'s `_recompute_summary_counts()` (M-003) both call — any change to the RECONCILED/MINOR_EXCEPTIONS/EXCEPTIONS_PRESENT thresholds here must stay consistent for both call sites to keep describing "the same live state" (see `_recompute_summary_counts()`'s own docstring on this point).

**Change Impact** — The sole source of truth for match/exception classification — any change here directly changes financial reconciliation outcomes for every statement, both on the next run and retroactively via re-match (the DELETE-then-rewrite means old results are not preserved once superseded).

**Callers** — M-003, M-019 (via `run_matching`), M-021, M-050
**Calls** — M-037 (`execute_sql`/`execute_query`), M-042 (`get_shop_owner`)
**Integration Points Used** — IP-008 (via M-037)
