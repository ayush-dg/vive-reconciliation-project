# ENH-011_BRIEF.md

**Enhancement ID:** ENH-011
**Title:** n8n Orchestration Wrapper
**Author:** TBD
**Date:** 2026-08-11
**Status:** [x] Draft | [ ] AI Review Complete | [ ] Signed Off

> **Backlog stub.** Captured now so intent/dependency notes from the initial
> backlog review aren't lost. Known Touch Points are not yet researched — that
> happens at Prompt 1.

---

## Enhancement Intent

Add scheduling, retries, and failure alerts around the existing pipeline using
n8n, without reimplementing pipeline logic inside n8n itself.

---

## Known Dependencies

None flagged at initial backlog review.

---

## Flagged Collision Risk

None flagged at initial backlog review.

---

## Known Constraints

n8n should orchestrate from outside by calling existing entry points
(`scripts/run_full_pipeline.py`, the job queue the worker polls) rather than
reimplementing pipeline logic. Must respect RULE-05 (the mock ERP generator stays
CLI-only — never gets an n8n-triggered HTTP path) and INV-05 (a naive retry policy
must not double-queue a job that's already `PROCESSING` for its filename).

---

## Out of Scope

TBD at Prompt 1.

---

## Engineer Sign-Off

[ ] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**Signed:**
**Date:**
