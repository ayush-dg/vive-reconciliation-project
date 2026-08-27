# ENH-008_BRIEF.md

**Enhancement ID:** ENH-008
**Title:** Audit Ledger Unification
**Author:** TBD
**Date:** 2026-08-11
**Status:** [x] Draft | [ ] AI Review Complete | [ ] Signed Off

> **Backlog stub — held until ENH-002 (Run Management Layer) lands.** Captured now
> so intent/dependency/collision notes from the initial backlog review aren't
> lost. Known Touch Points are not yet researched — that happens at Prompt 1.
> Exactly which two logs are being unified is not yet confirmed against live code
> (candidates: `ai_audit_log` and the `exception_dispositions` trail) — confirm at
> Prompt 1, don't assume.

---

## Enhancement Intent

Combine two separate logs into one clean, permanent record of every decision made
in the system — today decisions/dispositions appear to be split across more than
one table with no single authoritative ledger.

---

## Known Dependencies

**ENH-002 (Run Management Layer)** — needs a run concept to exist first, so
unified audit entries have something to anchor to.

---

## Flagged Collision Risk

**ENH-004 (Finish the Fabric Migration)** — flagged as possibly touching the same
file/table. `ai_audit_log` is one of the four Recon tables ENH-004 is migrating;
unifying its schema while its storage backend is also being moved is a genuine
same-surface risk. Needs Prompt 2 resolution — likely sequencing (migrate first,
then unify, or vice versa) rather than parallel build.

---

## Known Constraints

TBD at Prompt 1 — including confirming exactly which two logs this refers to.

---

## Out of Scope

TBD at Prompt 1.

---

## Engineer Sign-Off

[ ] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**Signed:**
**Date:**
