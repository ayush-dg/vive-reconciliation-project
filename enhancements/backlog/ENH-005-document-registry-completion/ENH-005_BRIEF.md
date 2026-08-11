# ENH-005_BRIEF.md

**Enhancement ID:** ENH-005
**Title:** Document Registry Completion
**Author:** TBD
**Date:** 2026-08-11
**Status:** [x] Draft | [ ] AI Review Complete | [ ] Signed Off

> **Backlog stub.** Captured now so intent/dependency/collision notes from the
> initial backlog review aren't lost. Known Touch Points are not yet researched —
> that happens at Prompt 1.

---

## Enhancement Intent

Properly track each uploaded PDF's status across its full life (received →
checked → done, etc.), rather than the current partial/implicit tracking.

---

## Known Dependencies

None flagged at initial backlog review.

---

## Flagged Collision Risk

**ENH-006 (Validation Service Hardening)** — flagged as possibly touching the
same file/table. Likely surface: both plausibly touch `document_intake_log`
and/or `notebooks/01_document_intake.py`'s validation gate — one is extending the
per-document status lifecycle, the other is adding new per-row validation checks
in roughly the same code path. Needs Prompt 2 resolution before both are built
concurrently.

---

## Known Constraints

TBD at Prompt 1. Needs to confirm the exact status vocabulary and whether this
extends the existing `document_intake_log` table (already migrated to a real SQL
database in Fabric item per `docs/Claude.md` v2.9) or introduces a new one — any
schema change goes through a new numbered migration file per RULE-12, on whatever
backend that table currently lives on.

---

## Out of Scope

TBD at Prompt 1.

---

## Engineer Sign-Off

[ ] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**Signed:**
**Date:**
