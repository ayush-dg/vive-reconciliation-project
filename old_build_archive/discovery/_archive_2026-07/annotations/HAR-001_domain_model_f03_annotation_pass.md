# HAR-001 — DOMAIN_MODEL.json F03 Annotation Pass (Entity/Attribute/StatusValue semantics)
**Checklist item:** N/A — this predates ANNOTATION_CHECKLIST.md (produced at Stage 3 only); this is the Session F "Engineer Annotation Pass" per bce_core.md Section 11.3.
**Engineer:** Ayush Kumar Sinha
**Date:** 2026-07-23

**Note on scope:** consolidated into one HAR covering all 23 originally-NOT_DETERMINABLE fields plus the `synonyms` note, rather than one HAR per field — a practical batching decision for a field-level annotation pass this size, not a deviation from the HAR pattern's traceability intent (every field's exact source and value is preserved individually below). No `PROJECT_MANIFEST.md` exists in this project (non-PBVI, Path A custodian-led) — the directory-registration step in bce_core.md Section 8 doesn't apply here.

## Raw Annotation

### A. Entity-level semantic properties (E-001 — Invoice)

> 1. business_definition: "A single line item on a vendor's monthly statement representing one unpaid or disputed charge -- a parts order, sublet repair, or towing charge -- that VIVE owes or has paid, identified by an invoice number the vendor assigns."
> 2. lifecycle_summary: "Received on a vendor PDF -> extracted -> normalized into Silver -> compared against internal ERP records -> resolved as matched or surfaced as an exception for AP review."
> 3. domain: "Accounts Payable / Vendor Reconciliation"
> synonyms: NOT DETERMINABLE FROM SOURCE -- no team-specific alternate naming confirmed yet.

### B. Attribute `null_semantic` values

> For B (null_semantic), items 4-9 and 11-17: apply the code-derived answers Claude (chat) provided — cite the specific functions (validate_invoice's required_fields, get_skip_reason, normalize_to_silver's fallback logic, etc.) as the source, not my personal knowledge.

(Applied as NOT_APPLICABLE for A-001, A-002, A-003, A-004, A-005, A-006, A-009, A-010, A-015, A-017, A-023, A-024, A-025 — see ENGINEER NOTE citations on each field in discovery/DOMAIN_MODEL.json, each naming the specific guaranteeing function/mechanism.)

> Item 10 (vendor_name ~424 nulls): don't annotate yet. First investigate — pull statement_id + source_file (no other content) for a sample of these null rows, and check whether they correlate with a specific extraction provider, an error path, or cache-hit runs specifically... Report what you find before we decide the null_semantic answer.

Investigation performed 2026-07-23 (see chat transcript): all 424 nulls trace to exactly two statement_ids (`STMT-1291E89D`, 234 rows, Fred_Beans_MidNJ_053126.pdf; `STMT-A00DDA29`, 190 rows, ASTCollex0526.pdf), neither of which has any row in `bronze_vendor_statement_raw`, `document_intake_log`, or `extraction_cache` — meaning neither was produced by `normalize_to_silver()` (which does nothing if no Bronze rows exist for that statement_id) or any live pipeline run. Both are single-timestamp bulk inserts, consistent with an orphaned test/seed script, not a defect in the live intake pipeline's `derive_vendor_name_from_filename()` fallback.

Engineer's final annotation, applied 2026-07-23:
> "ABSENT, confirmed isolated to two orphaned test-seed statement_ids (STMT-1291E89D, STMT-A00DDA29) with zero Bronze/intake-log/cache footprint — not a defect in the live intake pipeline's vendor_name fallback. Root cause of the seed data itself is not determinable (no git history to trace which script inserted it)."

### C. StatusValue `transition_trigger` values

> For C, items 18-22: confirmed terminal/non-transitioning, apply as drafted.
> Item 23 (PENDING -> POSTED trigger): apply this framing — "Not yet observed because the Mock ERP generator (RULE-06 placeholder) always assigns POSTED by default. PENDING exists in the schema for the eventual real NetSuite integration, where the real-world trigger would be VIVE's AP team or NetSuite marking the transaction posted. This is forward-looking design intent, not an observed behavior."

## BCE Artifact Updated

**Artifact:** DOMAIN_MODEL.json (Session F — not one of the seven core BCE artifacts, but subject to the same annotation discipline per bce_core.md Section 11.3)
**Section:** `nodes` array
**Fields:**
- E-001: `business_definition`, `lifecycle_summary`, `domain` (`synonyms` confirmed empty, noted in `extraction_note`)
- A-001, A-002, A-003, A-004, A-005, A-006, A-007, A-009, A-010, A-015, A-017, A-023, A-024, A-025: `null_semantic`
- SVV-001, SVV-002, SVV-003, SVV-004, SVV-005, SVV-006: `transition_trigger`

## ENGINEER NOTE Applied

All 23 fields updated in `discovery/DOMAIN_MODEL.json` with `[ENGINEER NOTE — 2026-07-23]` (or `[ENGINEER NOTE — 2026-07-23, code-derived]` for the 13 code-traced `null_semantic` values in category B) markers inline on each field, per the ENGINEER NOTE provenance convention (bce_core.md Section 8). Exact text as applied is visible directly in the JSON file — not reproduced in full here to avoid duplicating ~2,000 words of near-identical content; see the file for each field's precise wording and code citation.

## Resolution Log Entry

| ITEM-ID | Resolution type | Resolved by | Date | Evidence |
|---|---|---|---|---|
| DOMAIN_MODEL-F03-ANNOTATION | RESOLVED-ANNOTATION | Ayush Kumar Sinha | 2026-07-23 | HAR-001 |
