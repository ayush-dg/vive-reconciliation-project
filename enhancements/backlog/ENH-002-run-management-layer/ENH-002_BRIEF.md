# ENH-002_BRIEF.md

**Enhancement ID:** ENH-002
**Title:** Run Management Layer
**Author:** TBD
**Date:** 2026-08-11
**Status:** [x] Draft | [ ] AI Review Complete | [ ] Signed Off

> **Backlog stub — proposed for the earliest sprint that opens after this round of
> planning.** Captured now so intent/dependency/collision notes from the initial
> backlog review aren't lost. Known Touch Points are not yet researched — that
> happens at the Prompt 1 brief review gate, not here. Do not include in a Sprint
> Manifest collision surface analysis until Known Touch Points are filled in and
> the engineer moves this into an active sprint.

---

## Enhancement Intent

Today there is no explicit "start this month's reconciliation" concept. Jobs are
tracked per-PDF (`jobs` table, one row per file, per INV-05's per-filename
PROCESSING guard) with no parent entity grouping all the jobs, matches, and
exceptions that belong to one batch/period's work. This enhancement introduces
that concept — a run has its own lifecycle (started → processing → complete) and
becomes the boundary that other backlog items anchor to: work-item versioning
(ENH-003) and audit ledger unification (ENH-008) both depend on it existing first.

---

## Known Dependencies

None — this is foundational. ENH-003 and ENH-008 depend on this landing first;
build order should put this enhancement ahead of both.

---

## Flagged Collision Risk

**ENH-004 (Finish the Fabric Migration)** — flagged at initial backlog review as
possibly touching the same file/table. Likely surface: wherever the new run
entity's table lives, it lands on whatever `src/lakehouse/connection.py` is
currently routing Recon-classified tables to — and ENH-004 is actively changing
that routing. Needs explicit ownership/sequencing via Prompt 2 collision-surface
analysis before both are built in the same sprint by different engineers.

---

## Known Constraints

TBD at Prompt 1 review. One thing to resolve early: where a "run" boundary begins
and ends relative to the existing per-file `jobs` table, and whether that
boundary is itself a new table or a grouping column — this shapes both ENH-003
and ENH-008's design.

---

## Out of Scope

Does not change per-file job processing (`web/worker.py`, INV-05's one-PROCESSING-
job-per-filename guard) — a run is a grouping *above* jobs, not a replacement for
the existing per-job worker logic.

---

## Engineer Sign-Off

[ ] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**Signed:**
**Date:**
