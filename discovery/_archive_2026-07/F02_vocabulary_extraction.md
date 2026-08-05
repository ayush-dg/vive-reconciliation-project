STAGE-F2-DRAFT: VOCABULARY — 2026-07-23 — Produced by BCE Session F02 (CC)

Read `discovery/F01_structural_inventory.md` first — not sparse, proceeding with full extraction.

**Sources read:** live data in both databases (local SQLite `lakehouse/reconciliation.db`, and Azure SQL — aggregate `GROUP BY`/`COUNT` queries only, per standing engineer instruction from the Session A/E confidence-audit follow-up: no individual row content, vendor names, or invoice numbers queried here either). Cross-checked against the source code that writes each field (`src/matching/engine.py`, `notebooks/01_document_intake.py`, `web/queries.py`) to confirm every observed value's origin and to catch code-possible values that have never actually been written. No static seed/fixture files exist in this codebase (`config/mock_erp/scenario_config.json` controls *which* invoices get exceptions planted, not a vocabulary source itself); the two live databases serve as the "seed data" source for cardinality and null-frequency purposes.

---

## Per-Field Vocabulary

| Entity | Field | Observed Values | Source |
|---|---|---|---|
| `silver_reconciliation_standard` | `record_source` | `VENDOR_STATEMENT`, `INTERNAL_ERP` | Local DB (3031 / 1299 rows) — matches the CHECK constraint exactly; no third value possible or observed. |
| `silver_reconciliation_standard` | `document_type` | `VENDOR_STATEMENT`, `MOCK_ERP_EXTRACT` | Local DB. `MOCK_ERP_EXTRACT` is hardcoded literally in `normalize_erp_to_silver()` — not derived from any AI extraction. |
| `silver_reconciliation_standard` | `status` | `NULL` (VENDOR_STATEMENT side), `POSTED` (ERP side) | Local DB. `PENDING` is a valid code-possible value (`src/mock_erp/generator.py`: `status = "PENDING" if invoice_num in pending_posting else config.get("default_erp_status", "POSTED")`) but never observed in either database — no statement processed so far has used the `pending_posting` scenario config option. |
| `silver_reconciliation_standard` | `currency` | `USD` (VENDOR_STATEMENT side), `NULL` (ERP side) | Local DB. ERP-side currency is never populated — `normalize_erp_to_silver()` hardcodes it `None`; the field only carries a real value on the extraction side, always `"USD"` (also hardcoded, in every provider client's `_build_schema()`). No non-USD value observed or reachable from current code — every client hardcodes `"currency": "USD"`. |
| `gold_matched_invoices` | `match_status` | `MATCHED` | Local + Azure SQL (4,081 rows combined). Hardcoded literal in the INSERT statement in `run_matching()` — not a variable, so no other value is reachable through this code path at all. |
| `gold_matched_invoices` | `match_level` | `1` only | Local (1,299 rows) + Azure SQL (2,782 rows) — **`2` (RO number + amount fallback) has never fired in any recorded reconciliation run across either database**, despite being real, tested logic in `classify_match()`. See Naming Pattern Flags. |
| `gold_exceptions` | `match_status` | `EXCEPTION` | Azure SQL (62 rows; 0 locally). Hardcoded literal, same pattern as `gold_matched_invoices.match_status`. |
| `gold_exceptions` | `exception_reason` | `EXTRACTION_INCOMPLETE` (35), `Invoice Missing` (18), `Amount Mismatch` (9) | Azure SQL. `DUPLICATE_RECORD` is a fourth code-possible value (`web/queries.py action_review_item()`, when flagging a review-queue row whose `rejection_category` was `DUPLICATE_RECORD`) but has never been observed in either database. |
| `gold_exceptions` | `exception_status` | `OPEN` (60), `RESOLVED` (2) | Azure SQL. |
| `exception_dispositions` | `disposition_status` | `ACCEPTED` (1), `DISPUTED` (1) | Azure SQL (0 locally). CHECK constraint also permits `DUPLICATE`, `WRITE_OFF`, `PENDING` — **none of those three have ever been observed**; only 2 disposition rows exist in total across both databases. |
| `validation_document_review_queue` | `rejection_category` | `MISSING_MANDATORY_FIELD` (1,096), `DUPLICATE_RECORD` (472) | Local DB. Code permits two more values never observed: `INVALID_FIELD_TYPE` and `LOW_CONFIDENCE` (both are real `validate_invoice()` branches in `notebooks/01_document_intake.py`) — every review-queue row recorded so far came from either a missing required field or the duplicate-key check, never a type error or a sub-threshold confidence score. |
| `validation_document_review_queue` | `review_status` | `PENDING_REVIEW` (1,568, local) | Local DB. Code permits `APPROVED`/`FLAGGED` (`action_review_item()`) — neither has been observed; every review-queue row recorded locally is still sitting unreviewed. |
| `jobs` | `status` | `COMPLETED` (10, Azure SQL only — table absent locally, see F01 Divergence Flags) | Azure SQL. CHECK constraint also permits `PENDING`, `PROCESSING`, `FAILED` — none observed; every job recorded has completed successfully. |

---

## Cardinality Samples

| Relationship | Observed Cardinality | Sample Size | Notes |
|---|---|---|---|
| `silver_reconciliation_standard` (VENDOR_STATEMENT) → `gold_matched_invoices` / `gold_exceptions` | Not strictly 1:1 — see Naming Pattern Flags | 4,330 Silver rows (local) vs. 2,203 Bronze rows (local) | Silver row count exceeds Bronze row count for VENDOR_STATEMENT rows; a cache-hit re-run creates new Silver rows under a fresh `statement_id` without writing new Bronze rows under that same `statement_id` (see below). |
| `gold_exceptions` → `exception_dispositions` | Sparse — 2 of 62 exceptions (Azure SQL) have ever been disposed | 62 exceptions, 2 dispositions | Disposition workflow exists and works (schema, UI, resolve_exception all confirmed functional in Session A), but is lightly used in the data observed so far — consistent with early-stage/test usage, not a code defect. |
| `gold_matched_invoices.match_level` distribution | 100% Level 1 (exact invoice + amount), 0% Level 2 (RO + amount) | 4,081 matched rows combined | See Naming Pattern Flags — Level 2 has zero observed exercise despite being real, tested code. |

---

## Null Frequency

(`silver_reconciliation_standard`, local DB, 4,330 total rows — combines both `record_source` values)

| Entity | Field | Nullable (declared) | Null in Live Data | Notes |
|---|---|---|---|---|
| `silver_reconciliation_standard` | `vendor_name` | Yes (no NOT NULL) | 1,723 / 4,330 (40%) | All 1,299 `INTERNAL_ERP` rows are null by design (`normalize_erp_to_silver()` hardcodes `None` — "vendor_name not stored in ERP Bronze"). The remaining 424 nulls are on the `VENDOR_STATEMENT` side, where `notebooks/01_document_intake.py` has an explicit filename-derived fallback intended to guarantee a non-null value before Bronze is written — worth an annotation question at F03/engineer review: are these 424 rows from a code path that predates the fallback, or a second gap the fallback doesn't cover? Flagged, not resolved here. |
| `silver_reconciliation_standard` | `shop` | Yes | 2,136 / 4,330 (49%) | Expected — many vendor statements have no shop/location column at all (per RULES.md, this is vendor-layout-dependent, not an extraction failure). |
| `silver_reconciliation_standard` | `invoice_date` | Yes | 668 / 4,330 (15%) | |
| `silver_reconciliation_standard` | `ro_number` | Yes | 2,008 / 4,330 (46%) | Expected — not every vendor statement includes a repair-order column. |
| `silver_reconciliation_standard` | `po_number` | Yes | 4,261 / 4,330 (98%) | Almost never populated — PO number is a rarely-used field for this vendor mix. |
| `silver_reconciliation_standard` | `work_order_number` | Yes | 2,973 / 4,330 (69%) | |
| `silver_reconciliation_standard` | `credit` | Yes | 4,101 / 4,330 (95%) | Rarely populated — most vendor statements have no credit-memo line items in the observed sample. |
| `silver_reconciliation_standard` | `due_date` | Yes | 2,904 / 4,330 (67%) | |
| `silver_reconciliation_standard` | `posting_date` | Yes | 4,214 / 4,330 (97%) | `NOT_APPLICABLE` on the VENDOR_STATEMENT side by design (posting_date is an ERP-only concept, always `None` per `normalize_to_silver()`); on the ERP side it's populated whenever an `invoice_date` existed to compute a lag from (see `src/mock_erp/generator.py`) — the residual nulls are ERP rows whose source `invoice_date` was itself null. |
| `silver_reconciliation_standard` | `description` | Yes | 4,261 / 4,330 (98%) | Almost never populated on either side. |
| `silver_reconciliation_standard` | `amount`, `outstanding_amount`, `invoice_number`, `invoice_number_normalized`, `vendor_id`, `statement_date` | No nulls observed | 0 / 4,330 | Consistent with `validate_invoice()`'s required-field gate — rows missing these are diverted to the review queue before ever reaching Silver, not written with nulls. |

---

## Naming Pattern Flags

| Concept | Name in Source A | Name in Source B | Notes |
|---|---|---|---|
| Match tier / matching level | `match_level` (INTEGER, `gold_matched_invoices`) | "Level 1" / "Level 2" (prose, `config/matching/matching_rules.json`, RULES.md RULE-11, code comments) | Same concept, two representations — the integer is what's actually stored; the "Level N" phrasing is documentation/config convention only. Not a real disambiguation risk, just worth the domain model recording both. |
| Statement identity across a cache-hit re-run | `statement_id` (used as the primary de-facto entity key throughout Bronze/Silver/Gold) | — | **Real structural quirk, not just a naming issue.** `notebooks/01_document_intake.py`'s cache-hit path (`check_cache()` → `normalize_to_silver(cached_statement_id, statement_id, vendor_id)`) writes new Silver rows under a *new* `statement_id` by copying Bronze data that still lives under the *original* cached `statement_id` — no new Bronze rows are ever written for the new `statement_id`. This means `statement_id` is **not** a reliable join key from Silver back to Bronze in every case — only true for a fresh (non-cache-hit) extraction. This does not affect the confidence-fabrication findings already recorded (those were verified against statement_ids confirmed to have matching Bronze rows directly), but it is a real modeling nuance: `statement_id` functions as a "reconciliation run identity," not strictly as "the identity of the extraction event," and the two can diverge. Recommend Session F03 capture this as a `dissolution_semantic`/relationship-note candidate on the Invoice↔Bronze relationship, and flag as an ANNOTATION_CHECKLIST item (Type: OPEN_QUESTION) for engineer confirmation of intended behavior. |
| ERP posting status vs. review-queue status vs. job status vs. disposition status | Four independently-named status enums (`silver.status`/`bronze_internal_erp_raw.raw_status`, `validation_document_review_queue.review_status`, `jobs.status`, `exception_dispositions.disposition_status`) plus `gold_exceptions.exception_status` | — | Five distinct status vocabularies in this system, each governing a different lifecycle (ERP posting state, review-queue triage, job execution, human disposition, exception lifecycle). No naming collision, but worth flagging for Session F03 so each becomes its own `StatusVocabulary` node rather than being conflated into one. |

---

F02 is complete. `discovery/F02_vocabulary_extraction.md` must be committed and reviewed before F03 begins.
