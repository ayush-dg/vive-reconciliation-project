# ENH-003_BRIEF.md

**Enhancement ID:** ENH-003
**Title:** Statement Processing / Work-Item Versioning
**Author:** TBD
**Date:** 2026-08-11
**Status:** [x] Draft | [ ] AI Review Complete | [ ] Signed Off

> **Backlog stub — held until ENH-002 (Run Management Layer) lands.** Captured now
> so intent/dependency notes from the initial backlog review aren't lost. Known
> Touch Points are not yet researched — that happens at Prompt 1, not here.

---

## Enhancement Intent

Today, reprocessing a statement (e.g. after a corrected PDF re-upload) creates a
brand-new record instead of keeping a proper version history against the same
underlying work item. This enhancement adds that history so a reprocessed
statement retains its lineage rather than looking like an unrelated new document.

---

## Known Dependencies

**ENH-002 (Run Management Layer)** — needs a run concept to exist first, so a
version can be anchored to "which run produced this version."

---

## Flagged Collision Risk

None flagged at initial backlog review.

---

## Known Constraints

TBD at Prompt 1. Needs to define precisely what a "work item" is (per-file? per-
invoice-line?) and must interact carefully with RULE-02's extraction-cache-hit
logic (`notebooks/01_document_intake.py` — `check_cache()`) — reprocessing must
never be silently treated as a cache hit if the underlying document actually
changed.

---

## Out of Scope

Not a general-purpose event-sourcing rewrite of the pipeline — scoped narrowly to
the reprocessing-produces-a-disconnected-new-record gap.

---

## Engineer Sign-Off

[ ] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**Signed:**
**Date:**
