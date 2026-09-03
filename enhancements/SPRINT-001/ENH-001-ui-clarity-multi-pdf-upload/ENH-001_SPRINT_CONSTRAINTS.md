# ENH-001_SPRINT_CONSTRAINTS.md

**Enhancement ID:** ENH-001
**Title:** UI clarity fixes (Home/Upload/Document Detail) + multiple PDF upload
**Sprint:** SPRINT-001
**Engineer:** Vaishali
**Classification:** INDEPENDENT
**Produced by:** Sprint Lead from SPRINT-001_MANIFEST.md
**Date:** 2026-09-03

---

## Your Classification

**Role:** INDEPENDENT

You may begin Phase 1 immediately — there is no other enhancement in this sprint to
collide with, and no Foundation dependency gating your Phase 3 entry. You own the
entirety of your declared touch points by default (nothing to share), and there are no
surfaces belonging to another enhancement that you must avoid. The one thing this
classification does *not* mean is "no discipline required" — the watchpoint below and
the BCE constraints still apply in full.

---

## Surfaces You Own

No owned surfaces — no other enhancement in this sprint touches your build surface.

---

## Surfaces You Must Not Touch

No restricted surfaces for this sprint.

---

## Your Phase 3 Gate

Not applicable — INDEPENDENT classification.

---

## Your Watchpoints

| ID | Surface | What You Must Confirm in Phase 1 | Escalate If |
|---|---|---|---|
| ~~WP-001~~ | ToastProvider (`MODULE_CONTRACTS.md` → M-083) | **RESOLVED 2026-09-03** — running success-only counter toast ("N/10 uploaded"), reusing existing `toastStore.ts` primitives, no `M-083` change. Full decision in `ENH-001_BRIEF.md` Known Constraints. | N/A — resolved |

No open watchpoints remain for this enhancement.

---

## BCE Constraints

**Do not update `discovery/` artifacts during your enhancement build or close-out.**

Your per-enhancement BCE deliverable is `ENH-001_BCE_IMPACT.md` only — produced at
Phase 8 Part 2B close-out. Updating `discovery/` for a single enhancement mid-sprint is
a process violation. Record BCE knowledge in Verification Record BCE Impact sections
and in `ENH-001_BCE_IMPACT.md`. The Sprint Lead reconciles all impact logs and updates
`discovery/` once at sprint close-out.

---

## Escalation Rules

1. Any Phase 1 discovery that surfaces a new collision not in the Sprint Manifest →
   stop planning, escalate to Sprint Lead immediately before continuing
2. Any watchpoint confirmed as a collision →
   stop planning, escalate to Sprint Lead immediately
3. Any build divergence requiring amendment to your BCE impact log →
   notify Sprint Lead unconditionally — do not self-assess downstream impact

---

## Sprint Lead Contact

**Sprint Lead:** Vaishali
**SPRINT-001_MANIFEST.md:** `enhancements/SPRINT-001/SPRINT-001_MANIFEST.md`
**SPRINT-001_LOG.md:** `enhancements/SPRINT-001/SPRINT-001_LOG.md`
