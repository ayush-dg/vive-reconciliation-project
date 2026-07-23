## C17 — matching engine
ID: M-036
Layer: pipeline
Source file: src/matching/engine.py

**Module** — matching engine
**ID** — M-036
**Layer** — pipeline
**Primary Responsibility** — Deterministic 2-level matching engine comparing Silver VENDOR_STATEMENT rows against Silver INTERNAL_ERP rows. Zero AI (RULE-03) — a hard invariant, confirmed by direct source read: no import, call, or reference to any AI client anywhere in this file.

**Inputs** — `run_matching(statement_id: str, rules_path="config/matching/matching_rules.json") -> dict`.

**Outputs** — Writes `gold_matched_invoices`, `gold_exceptions`, `gold_reconciliation_summary` for the given `statement_id` (idempotent re-run: existing Gold rows for that `statement_id` are deleted first, **except** `EXTRACTION_INCOMPLETE` exceptions, which are explicitly exempt from the delete since matching has no Silver data to reclassify them from).

**Public Interface**
- `load_matching_rules(config_path) -> dict`
- `amounts_match(stmt_amount, erp_amount, tolerance_pct, tolerance_abs) -> bool`
- `classify_match(stmt_invoice, erp_candidates, tolerance_pct, tolerance_abs) -> dict` — the core matching decision, per-invoice.
- `run_matching(statement_id, rules_path=...) -> dict` — the full run: reads Silver, matches every statement invoice, writes Gold.

**Error Behaviour** — `run_matching()` raises `ValueError` (uncaught, deliberately fail-fast) if either side has zero Silver rows for the `statement_id` — "Run 02_generate_mock_erp.py first" for the ERP-side case. No other explicit error handling; a DB write failure mid-loop would leave a partial Gold write for that statement (no wrapping transaction across the whole run — each `execute_sql()` call commits independently, per M-033).

**Known Fragility**
- **Level 2 (RO number + amount) has never fired in any recorded reconciliation run** across either database (confirmed via live query during F02) — 100% of 4,081+ matched invoices combined are Level 1 (exact invoice number + amount). The logic is real and reachable (confirmed by reading `classify_match()`'s actual branching) but has zero observed exercise — worth flagging for Session D (invariant candidate: is Level 2 actually needed, or is it defensive code for a vendor-formatting scenario that hasn't occurred yet?).
- **The Level 1 vs. Level 2 fallback order is deliberately NOT a "fuzzy prefix" match** — RULE-11's rationale (a truncated-prefix heuristic previously cross-matched unrelated invoices sharing a common prefix, silently hiding genuinely missing invoices) is preserved as an explicit code comment directly above the Level 2 branch, confirmed present and matching RULES.md's account exactly.
- **`available_erp` is recomputed by list comprehension on every statement invoice** (`[e for e in erp_rows if e["record_id"] not in matched_erp_ids]`) — an O(n²) pattern for `n` statement invoices against `m` ERP rows; not a correctness issue at current data volumes (hundreds of rows), but a real scaling consideration if statement sizes grow substantially.

**Change Impact** — `classify_match()`'s return shape (`match_status`, `match_level`, `matched_erp`, `exception_reason`, `exception_erp_amount`) is depended on directly by `run_matching()`'s Gold-write logic — any change to one requires updating the other in the same commit.

**Callers** — M-016 (`notebooks/03_run_matching.py`), M-018 (`scripts/run_full_pipeline.py`, direct import)
**Calls** — M-033 (`execute_sql`, `execute_query`)
**Integration Points Used** — IP-008 (Lakehouse database)
