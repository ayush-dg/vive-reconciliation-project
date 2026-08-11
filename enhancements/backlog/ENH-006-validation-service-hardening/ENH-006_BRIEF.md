# ENH-006_BRIEF.md

**Enhancement ID:** ENH-006
**Title:** Validation Service Hardening
**Author:** TBD
**Date:** 2026-08-11
**Status:** [x] Draft | [ ] AI Review Complete | [ ] Signed Off

> **Backlog stub.** Captured now so intent/dependency/collision notes from the
> initial backlog review aren't lost. Known Touch Points are not yet researched —
> that happens at Prompt 1.

---

## Enhancement Intent

Add a check that catches when extracted invoice numbers don't add up to the
statement total, plus other data-quality checks — extending
`notebooks/01_document_intake.py`'s `validate_invoice()` gate and
`config/validation/extraction_rules.json`.

---

## Known Dependencies

None flagged at initial backlog review.

---

## Flagged Collision Risk

**ENH-005 (Document Registry Completion)** — same surface risk as noted in
ENH-005's brief: both plausibly touch `document_intake_log` and/or the intake
validation gate. Needs Prompt 2 resolution before both are built concurrently.

---

## Known Constraints

Must not weaken INV-01 (confidence threshold), INV-03 (no summary rows ingested
as invoices), or INV-04 (`invoice_number`/`outstanding_amount` never null in
Silver). New checks are additive; any row failing a new check must still route to
human review, never silently drop — consistent with RULE-10's "never silently
succeed" pattern already established for OCR-derived rows.

---

## Out of Scope

TBD at Prompt 1.

---

## Engineer Sign-Off

[ ] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**Signed:**
**Date:**
