# ENH-003_BRIEF.md

**Enhancement ID:** ENH-003
**Title:** Split front end and back end (not two Container Apps)
**Author:** Vaishali
**Date:** 2026-09-03
**Status:** [x] Draft — NOT READY for brief review gate, see note below

---

## Enhancement Intent

**This brief is intentionally incomplete — recorded to hold the ENH-003 slot in the
backlog, not because it's ready for Phase 1.** As given: "split front and backend, not two
container apps." This reads as a deployment/infrastructure architecture change, not
application code, and is currently ambiguous between two different meanings:

(a) The app is currently deployed as two separate Container Apps, and the ask is to
    consolidate/restructure that — i.e. stop using two Container Apps.
(b) The app is currently one thing, and the ask is to split it into front/back — but
    explicitly *not* via two separate Container Apps, implying some other split
    mechanism (e.g. one Container App running separate front/back processes, or a
    different Azure service entirely).

This must be clarified by the engineer before Known Touch Points, Known Constraints, or
Out of Scope can be written honestly — writing them now would mean guessing at both the
problem and the target architecture.

---

## Known Touch Points

Not yet determinable — depends entirely on which reading above is correct, and on
infrastructure/deployment configuration that isn't captured in any BCE artifact (the
seven discovery artifacts describe application code structure, not Azure deployment
topology).

---

## Known Constraints

| Constraint | Type | Notes |
|---|---|---|
| Meaning of "split front and backend, not two container apps" must be clarified first | MANDATORY | Blocking — see Enhancement Intent. |
| Whether this is even PBVI/ENH-NNN-governed work at all | MANDATORY | Worth deciding explicitly once the intent is clear. If this is a pure infrastructure/ops change that doesn't touch `src/`, `migrations/`, or any invariant, the sprint/enhancement machinery (which is built around code-level changes traced to MODULE_CONTRACTS.md/TOPOLOGY.md entries) may not be the right vehicle for it — it might belong outside this process entirely. |

---

## Out of Scope

Not yet determinable — same reason as Known Touch Points.

---

## Engineer Sign-Off
[ ] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**NOT SIGNED — this brief should not be signed off or submitted to a brief review gate
until the Enhancement Intent ambiguity above is resolved.**

**Signed:** _________________________
**Date:** ___________
