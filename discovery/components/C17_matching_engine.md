## C17 — matching engine
ID: M-036
Layer: pipeline
Source file: src/matching/engine.py
Rewritten: 2026-07-25 scoped BCE refresh (match confidence scoring added 2026-07-24, Step 7)

**Module** — matching engine
**ID** — M-036
**Layer** — pipeline
**Primary Responsibility** — Deterministic 2-level matching engine comparing Silver VENDOR_STATEMENT rows against Silver INTERNAL_ERP rows, now also scoring a `match_confidence` for every row it writes. Zero AI (RULE-03/IC-3) — **re-confirmed this pass**: the new scoring functions (`score_match_confidence`/`score_exception_confidence`) are pure lookup-table functions keyed on `match_level`/amount-exactness/`exception_reason` string — no model call, no import of any AI client anywhere in this file. See `discovery/MODULE_CONTRACTS.md` cross-cutting finding #9.

**Inputs** — `run_matching(statement_id: str, rules_path="config/matching/matching_rules.json") -> dict` — unchanged signature.

**Outputs** — Writes `gold_matched_invoices`, `gold_exceptions`, `gold_reconciliation_summary` for the given `statement_id` (idempotent re-run: existing Gold rows for that `statement_id` are deleted first, except `EXTRACTION_INCOMPLETE` exceptions). **New as of 2026-07-24:** every `gold_matched_invoices` and `gold_exceptions` row now also carries a `match_confidence` score (migration `008_add_match_confidence.sql`), and every `gold_exceptions` row now also carries a `shop_owner` (migration `009_add_routing_aging.sql`, looked up via M-048).

**Public Interface**
- `load_matching_rules(config_path) -> dict` — unchanged
- `amounts_match(stmt_amount, erp_amount, tolerance_pct, tolerance_abs) -> bool` — unchanged
- **`score_match_confidence(match_level, stmt_amount, erp_amount) -> float` (new)** — looks up `MATCH_CONFIDENCE[(match_type, amount_status)]`, where `match_type` comes from `MATCH_LEVEL_TO_TYPE` (`{1: "INVOICE", 2: "RO"}`, falling back to `"FUZZY"` for any other level — none exist today) and `amount_status` is `"EXACT"` or `"TOLERANCE"` from `_amount_status()`.
- **`score_exception_confidence(exception_reason) -> float` (new)** — looks up `EXCEPTION_MATCH_CONFIDENCE`, falling back to `0.50` (the same value as its `EXTRACTION_INCOMPLETE` entry) for any reason not in the table, e.g. `DUPLICATE_RECORD`.
- **`_amount_status(stmt_amount, erp_amount) -> str` (private, new)** — `"EXACT"` if the two amounts are equal within `EXACT_AMOUNT_EPSILON` (0.005, a float-representation-noise guard, not a business tolerance), else `"TOLERANCE"`. Only meaningful once `amounts_match()` has already confirmed the amounts are within the matching engine's configured *business* tolerance — never needs to express "doesn't match at all."
- `classify_match(stmt_invoice, erp_candidates, tolerance_pct, tolerance_abs) -> dict` — the core matching decision, per-invoice. Unchanged.
- `run_matching(statement_id, rules_path=...) -> dict` — the full run: reads Silver, matches every statement invoice, writes Gold. Now also calls `score_match_confidence()`/`score_exception_confidence()` and M-048's `get_shop_owner()` per row written.

**Error Behaviour** — `run_matching()` raises `ValueError` (uncaught, deliberately fail-fast) if either side has zero Silver rows for the `statement_id` — unchanged. No other explicit error handling; a DB write failure mid-loop would leave a partial Gold write for that statement — unchanged.

**Known Fragility**
- **Level 2 (RO number + amount) has never fired in any recorded reconciliation run** — unchanged finding, not re-verified this pass (out of scope for this targeted refresh).
- **The Level 1 vs. Level 2 fallback order is deliberately NOT a "fuzzy prefix" match** — unchanged.
- **`available_erp` is recomputed by list comprehension on every statement invoice** — unchanged, O(n²) pattern.
- **New: `MATCH_CONFIDENCE`'s table includes `"PO"` and `"FUZZY"` match-type entries that `classify_match()` cannot currently produce** — there is no PO-based matching level, and the fuzzy-prefix level was deliberately removed (see the code comment above the Level 2 branch, RULE-11). Confirmed deliberate, not dead code masquerading as coverage: the table is sized for match types this engine doesn't produce yet so it won't need to change again the moment one of those levels is added. `("INVOICE", "MISMATCH")` is similarly unreachable today, since an invoice-number match with a mismatched amount always becomes an "Amount Mismatch" `EXCEPTION`, never a `MATCHED` row with that tier.
- **New: two independently-scaled meanings share one column name.** `gold_matched_invoices.match_confidence` (how reliable the match itself is) and `gold_exceptions.match_confidence` (how confident the system is the row is a genuine exception, not a matching error) are deliberately different scales scored by different tables (`MATCH_CONFIDENCE` vs. `EXCEPTION_MATCH_CONFIDENCE`) — a future consumer reading both columns as if they were the same measurement would draw a wrong conclusion (e.g. comparing a `0.90` "Invoice Missing" exception confidence directly against a `0.95` matched-row confidence as if higher always means "more certain the invoice is correctly accounted for").
- **New, confirmed by this pass, not by the original 2026-07-24 build:** `get_high_confidence_exception_count()`'s consumer (`web/queries.py`, M-011) defaults its threshold to `0.99` — above every value `EXCEPTION_MATCH_CONFIDENCE` can currently produce (`0.90` max). This engine's own scoring table is therefore not the source of that dormancy; it's a deliberate conservative choice made one layer up, in M-011/the bulk-approve feature. Noted here for anyone reading this file in isolation and expecting a `0.90`-scored exception to ever actually trigger bulk-approve at the shipped default.

**Change Impact** — `classify_match()`'s return shape is depended on directly by `run_matching()`'s Gold-write logic — unchanged. New: `score_match_confidence()`/`score_exception_confidence()`'s output feeds directly into `web/queries.py`'s `get_high_confidence_exception_count()`/`bulk_approve_exceptions()` (M-011) — changing either scoring table's values would directly change which exceptions become eligible for bulk approval, without any code change needed in M-011 itself.

**Callers** — M-016 (`notebooks/03_run_matching.py`), M-018 (`scripts/run_full_pipeline.py`, direct import), **M-011 (`web/queries.py:action_review_item()`, new — calls `score_exception_confidence()` directly, not via `run_matching()`)**
**Calls** — M-033 (`execute_sql`, `execute_query`), **M-048 (`get_shop_owner`, new)**
**Integration Points Used** — IP-008 (Lakehouse database)
