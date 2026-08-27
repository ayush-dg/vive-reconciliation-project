# F02 — Vocabulary Extraction — VIVE Reconciliation
Produced by: BCE Session F02 (CC)
Date: 2026-08-05

**Sources read:** No seed data, fixture files, GraphQL/OpenAPI schema, or `tests/` fixtures with representative production-shaped data were found in this codebase (`sample_data/` holds PDF inputs, not database fixtures; no local `lakehouse/reconciliation.db` exists in this checkout to query). Vocabulary values below are drawn from **direct code read** — every literal string a write site actually inserts/updates, and every value a `CHECK` constraint declares — not from sampled live data. This is narrower evidence than seed-data sampling would give (code shows what the system *can* write, not what it *has* written), and is marked as such throughout.

---

## Per-Field Vocabulary

| Entity | Field | Observed Values | Source |
|---|---|---|---|
| `silver_reconciliation_standard` | `record_source` | `VENDOR_STATEMENT`, `INTERNAL_ERP` | CHECK constraint (migration 001) + confirmed as the only two literals ever inserted (`notebooks/01_document_intake.py`, `src/mock_erp/generator.py`) |
| `gold_matched_invoices` | `match_status` | `MATCHED` (only value — hardcoded literal in the INSERT, `src/matching/engine.py:313`) | Code read |
| `gold_matched_invoices` | `match_level` | `1`, `2` (integer, not string — `MATCH_LEVEL_TO_TYPE = {1: "INVOICE", 2: "RO"}`) | `src/matching/engine.py:86` |
| `gold_exceptions` | `match_status` | `EXCEPTION` (only value — hardcoded literal, `src/matching/engine.py:347`) | Code read |
| `gold_exceptions` | `exception_reason` | `Invoice Missing`, `Amount Mismatch` (matching engine), `EXTRACTION_INCOMPLETE` (intake skip path), `DUPLICATE_RECORD` (review-queue flag path) | `src/matching/engine.py:186,220`; `notebooks/01_document_intake.py:269`; `web/queries.py:1185-1187` |
| `gold_exceptions` | `exception_status` | `OPEN` (insert default and every write site), `RESOLVED` (`resolve_exception()`) | `web/queries.py:522-540` |
| `gold_exceptions` | `escalation_status` | `NONE` (DEFAULT, migration 009), `ESCALATED` (`escalate_exception()`) | `web/queries.py:543-555` |
| `bronze_internal_erp_raw` / `silver_reconciliation_standard` (INTERNAL_ERP side) | `raw_status` / `status` | `POSTED` (config `default_erp_status`), `PENDING` (mock ERP's `pending_posting` controlled exception) | `src/mock_erp/generator.py:139-141`; `config/mock_erp/scenario_config.json` |
| `validation_document_review_queue` | `review_status` | `PENDING_REVIEW` (DEFAULT), `APPROVED`, `FLAGGED` | `web/queries.py:1160-1183` |
| `validation_document_review_queue` | `rejection_category` | `MISSING_MANDATORY_FIELD`, `INVALID_FIELD_TYPE`, `LOW_CONFIDENCE` (all three derived from `validate_invoice()`'s reason string, split on `:`), `DUPLICATE_RECORD` (intake's own duplicate-key check) | `notebooks/01_document_intake.py:96-129,290-329,763-769` |
| `exception_dispositions` | `disposition_status` | Declared (CHECK): `ACCEPTED`, `DISPUTED`, `DUPLICATE`, `WRITE_OFF`, `PENDING`. **Directly confirmed as actually written:** `ACCEPTED` only (`bulk_approve_exceptions()`'s hardcoded literal, `web/queries.py:671`). The single-exception action path (`exceptions_action()` router, `web/routers/exceptions.py:151-169`) passes an `action` form field straight through as `disposition_status` with no server-side enum validation — its actual runtime values depend on the HTML form's button values in `web/templates/exceptions_review.html`, **not read this session** (see `INTAKE_SUMMARY.md`'s Documents Reviewed — templates were not opened). Flagged as a **NOT_DETERMINABLE-from-backend-code-alone** case, not assumed to be the full CHECK set. |
| `jobs` | `status` | `PENDING` (CHECK/DEFAULT), `PROCESSING` (`claim_next_pending_job()`), `COMPLETED`, `FAILED` (`update_job_status()` call sites in `web/worker.py`) — all 4 declared values confirmed actually written | `web/queries.py:761-812`; `web/worker.py:80-110` |
| `users` | `is_active` | `1` (DEFAULT and only value ever written — no code path sets it to `0`; `delete_user_by_email()` does a hard `DELETE`, not a soft-deactivate) | `migrations/004_add_users_table.sql`; `web/queries.py:730-742` |

---

## Cardinality Samples

**No live seed data exists in this checkout to sample actual cardinality from** (see Sources note above). The relationships below are inferred from query/write-site *logic*, not observed data frequency — recorded as a structural approximation, not a true cardinality sample, and should be re-derived from real data once a populated environment is available.

| Relationship | Observed Cardinality (inferred from code logic) | Sample Size | Notes |
|---|---|---|---|
| Statement → Silver VENDOR_STATEMENT rows | ONE_TO_MANY | N/A — no live data | One statement_id normalizes to many invoice lines. |
| Silver VENDOR_STATEMENT row → Gold outcome | ONE_TO_ONE (mutually exclusive: matched XOR exception) | N/A | Enforced by `classify_match()`'s control flow returning exactly one branch per statement line, not by a database constraint. |
| Silver INTERNAL_ERP row → Gold match | ZERO_OR_ONE | N/A | `matched_erp_ids` set in `run_matching()` prevents the same ERP row being consumed twice; an ERP row with no statement-side match simply has zero matches, untracked as an entity. |
| `gold_exceptions` row → `exception_dispositions` rows | ONE_TO_MANY (potentially) | N/A | The lookup key `(vendor_name, invoice_number, reason_code)` is not unique-constrained — nothing in the schema prevents more than one disposition being recorded against the same logical exception over time (e.g. re-flagged, re-disposed on a later run). |
| `jobs` row → `document_intake_log`/`gold_reconciliation_summary` row | ZERO_OR_ONE | N/A | A FAILED job before Step 7 of intake has no `statement_id` at all, hence no downstream row. A cache-hit job reuses a prior `statement_id`'s Bronze but gets its own new `silver`/`gold` rows without a fresh `document_intake_log` row (see F01 Relationship Inventory). |

---

## Null Frequency

**Not determinable this session — no live database exists in this checkout to query actual null rates.** Every column's nullability below is the *declared* schema state only (no live-data cross-check performed):

| Entity | Field | Nullable (declared) | Null in Seed Data | Notes |
|---|---|---|---|---|
| `silver_reconciliation_standard` | `invoice_number` | Yes (schema) | NOT_DETERMINABLE — no live data | Application-layer guarantee (INV-04) says this should never actually be null in practice — see F01's Constraint Inventory note. Worth confirming against real data once available, since the guarantee lives in code, not the schema. |
| `silver_reconciliation_standard` | `outstanding_amount` | Yes (schema) | NOT_DETERMINABLE | Same INV-04 note as above. |
| `gold_matched_invoices` / `gold_exceptions` | `match_confidence` | Yes (added migration 008, no backfill) | NOT_DETERMINABLE | Rows written *before* migration 008, plus a couple of write sites migration 008 didn't cover (e.g. `DUPLICATE_RECORD` exceptions per `web/queries.py:1189-1191`'s own comment), are expected to be NULL by design — this is a genuine, intentional "always null in some rows" case, not a data-quality gap. |
| `gold_exceptions` | `shop_owner` | Yes (migration 009) | NOT_DETERMINABLE | `get_shop_owner()` (`src/shop_owners.py`) returns `None` for any vendor_id not in `config/shop_owners.json`'s placeholder mapping — by the config's own docstring, most vendor_ids are expected to miss today. A high null rate here is expected, not a defect. |
| `jobs` | `statement_id`, `vendor_name` | Yes | NOT_DETERMINABLE | Stay NULL for any job that fails before the pipeline determines them (see migration 005's own header comment) — an always-possible, not merely occasional, null case. |

---

## Naming Pattern Flags

| Concept | Name in Source A | Name in Source B | Notes |
|---|---|---|---|
| Processing/lifecycle state | `jobs.status` (PENDING/PROCESSING/COMPLETED/FAILED) | `gold_exceptions.exception_status` (OPEN/RESOLVED) | `gold_exceptions.escalation_status` (NONE/ESCALATED) | `gold_matched_invoices.match_status` / `gold_exceptions.match_status` (single hardcoded literals, not real vocabularies) | `exception_dispositions.disposition_status` (ACCEPTED/DISPUTED/DUPLICATE/WRITE_OFF/PENDING) | `validation_document_review_queue.review_status` (PENDING_REVIEW/APPROVED/FLAGGED) — **seven distinct fields across five tables all named `*status`, each with an independent, non-overlapping vocabulary.** Strong disambiguation candidate for the annotation pass; a planning AI reading "status" without this context would reasonably assume one shared meaning. |
| Confidence score, same column name | `gold_matched_invoices.match_confidence` — *how reliable a match is* | `gold_exceptions.match_confidence` — *how confident the system is that an exception is genuine, not a matching error* | Already explicitly documented in `src/matching/engine.py`'s own comments (`MATCH_CONFIDENCE` vs `EXCEPTION_MATCH_CONFIDENCE`, two distinct scales stored under one shared column name) — carried here as a formal disambiguation note for `DOMAIN_MODEL.json`, not a newly discovered issue. |
| Vendor identity | `vendor_id` | `vendor_name` | `vendor_id` is not an independently assigned identifier — it is deterministically *derived* from `vendor_name` at write time (`vendor_name.upper().replace(" ", "_")...`, `notebooks/01_document_intake.py:719`). The two look like a classic id/label pair but are actually one piece of information in two casings. |
| Disposition lookup key shape | `exception_dispositions`'s actual FK-equivalent: `(vendor_name, invoice_number, reason_code)` | Every other table's FK-equivalent: a single UUID (`statement_id`, `record_id`, `exception_id`, etc.) | Called out once already in F01's Relationship Inventory — repeated here because it is also a genuine naming/shape inconsistency worth flagging for entity-relationship annotation, not just a database-design note. |
| Amount vs. outstanding amount | `amount` (original charge) | `outstanding_amount` (what's still owed) | On vendors whose statements carry only one amount column, `validate_invoice()` explicitly copies one into the other as a fallback (`notebooks/01_document_intake.py:103-104`) — meaning a single stored value can legitimately represent either concept depending on the source vendor's layout. Not a bug; a real semantic ambiguity worth an Attribute-level `disambiguation_note`. |

---

F02 is complete. `discovery/F02_vocabulary_extraction.md` must be committed and reviewed before F03 begins.
