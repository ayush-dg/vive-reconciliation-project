# SPRINT-002_GUIDE.md

**Sprint:** SPRINT-002 (proposed — not yet formally initiated, see "What this guide is not" below)
**Team:** Ayush Kumar Sinha + Vaishali Rao Yellur, both building this sprint
**Scope:** ENH-002, ENH-010, ENH-011, ENH-013, ENH-014 (5 items, per the
"Proposed Backlog Grouping" note in `enhancements/REGISTRY.md`)
**Written:** 2026-08-11

---

## What this guide is not

This is a working guide to split effort and sequence work sensibly. It does
**not** substitute for this project's own process gates — it tells you when to
run them, not skip them:

- Every brief below is still a **Draft stub** in `enhancements/backlog/` with
  Known Touch Points marked TBD. **Prompt 1** (real touch-point research
  grounded in `discovery/` + live code, then Engineer Sign-Off) has not run for
  any of these five yet.
- **Prompt 2** (collision-surface analysis) has not run across this specific
  set of five. Nothing in this guide's ownership split is a substitute for that
  — it's an informed guess to unblock day-one work, not an adjudicated result.
- `SPRINT-002_LOG.md` and `SPRINT-002_MANIFEST.md` don't exist yet. Formal
  Sprint CC Initiation ("Initiate sprint SPRINT-002" in CC) is a separate,
  deliberate step — do it once both briefs are signed off, mirroring how
  SPRINT-001 ran.

Do Prompt 1 first, on both your assigned items, before writing any code.

---

## Ownership split

| ENH | Title | Owner | Why |
|---|---|---|---|
| **ENH-002** | Run Management Layer | **Ayush** | Foundational — everything in SPRINT-003 (ENH-003, ENH-008) is blocked on this landing. Touches `jobs`/worker/lakehouse layer, which the commit history shows Ayush already owns end to end. This is the sprint's critical path — start it day one. |
| **ENH-011** | n8n Orchestration Wrapper | **Ayush** | Wraps existing entry points (`scripts/run_full_pipeline.py`, the worker's job queue) that Ayush already built. Natural pairing with ENH-002 since both touch job lifecycle — but build it *after* ENH-002's schema stabilizes, not concurrently, so it isn't orchestrating around a moving target. |
| **ENH-010** | Access Control Hardening | **Vaishali** | Needs a Sprint-Lead-level call on the RULE-08 question (does "permissions for reviewers" mean amending the no-role-split rule, or just removing the hardcoded fallback + hardening login?) before the build scope is even fixed — a natural fit for the Sprint Lead role. Fully independent otherwise; safe to start day one. |
| **ENH-013** | Files/SharePoint Export | **Vaishali** | New external integration, independent of core pipeline internals — good parallel-track work while Ayush is deep in ENH-002. Note at Prompt 1: confirm what gets exported this sprint, since ENH-012 (Power BI reporting) isn't in scope yet — likely scoped to existing report artifacts (`notebooks/04_generate_report.py` output), not a full BI export. |
| **ENH-014** | Email/Notification Alerts | **Decide at the Week 1 sync** (see below) | Its dependency on ENH-002 is unconfirmed — the brief flags this as "TBD, confirm at Prompt 1." Smallest item in the sprint; don't assign it in isolation, decide once you know whether it needs ENH-002's run concept or can build against the existing `batch_id` from ENH-001. |

None of the four independent items (ENH-002, ENH-010, ENH-011, ENH-013) were
flagged as colliding with each other in the initial planning pass — that's what
lets two people build in parallel here. Confirm that holds once Prompt 2
actually runs.

---

## Suggested sequence

Adjust the exact days to your real timebox — the *order* matters more than the
calendar.

**Days 1-2 — gate work, both of you:**
- Each of you runs Prompt 1 on your two assigned briefs: real touch-point
  research (grep the actual code, check `discovery/MODULE_CONTRACTS.md` /
  `discovery/ID_REGISTRY.md` for the relevant M-NNN entries), fill in Known
  Constraints, sign off.
- Run Prompt 2 together as a short joint session across all five signed-off
  briefs, even the ones the initial planning pass didn't flag as colliding —
  Prompt 2 checks against `discovery/` artifacts, which is more rigorous than a
  one-line description.
- Once both briefs pass, do the formal Sprint CC Initiation and create
  `SPRINT-002_LOG.md` / `SPRINT-002_MANIFEST.md` (copy the SPRINT-001 pattern).

**Days 2+ — build, in parallel:**
- **Ayush** starts ENH-002.
- **Vaishali** starts ENH-010 (resolve the RULE-08 scope question first — don't
  let it get decided implicitly by whatever gets coded) and/or ENH-013.

**Mid-sprint sync (trigger: as soon as ENH-002's schema/API shape is stable
enough to describe, not on a fixed day):**
- Ayush shares the run entity's shape with Vaishali.
- Together, decide ENH-014's real scope: build against the new run concept, or
  against the existing `batch_id` if that's sufficient. This is the one
  decision point that unblocks the last item.

**Back half of the sprint:**
- **Ayush:** finish ENH-002, then ENH-011 once ENH-002's job/run relationship
  is settled.
- **Vaishali:** finish ENH-010 and ENH-013, then take ENH-014 (or build it
  jointly with Ayush if it turns out to need close coordination with ENH-002).

**End of sprint — Sprint Integration Check:**
- Integration-test ENH-002 + ENH-011 together (both touch job lifecycle).
- Integration-test ENH-002 + ENH-014 together (run/batch boundary).
- Confirm INV-05 (one PROCESSING job per filename) still holds after all four
  build-track items land — this is the invariant most likely to be touched
  incidentally by ENH-002 and ENH-011 both.

---

## Watchpoints — check for these actively, don't just build past them

- **ENH-002 ↔ ENH-011:** n8n's retry logic must not conflict with INV-05 or
  with whatever new run-boundary semantics ENH-002 introduces. Same owner
  (Ayush) for both reduces risk, but call this out explicitly at the handoff
  between the two rather than assuming continuity carries it.
- **ENH-002 → SPRINT-003:** whatever table/schema decision ENH-002 lands on
  needs to be reflected in ENH-004's (Fabric migration) and ENH-008's (Audit
  Ledger) Known Touch Points before *those* briefs go through Prompt 1 next
  sprint — don't let that update get lost between sprints.
- **ENH-010:** don't let "permissions for reviewers" quietly become role tiers
  without an explicit RULE-08 amendment recorded in `RULES.md` — same
  transparency standard the INV-01/INV-02 amendments were held to. If Vaishali
  decides RULE-08 needs to change, record it there, don't just code around it.
- **ENH-014:** don't start real implementation before the mid-sprint sync
  answers the ENH-002 dependency question — building against a moving target
  risks rework.

---

## Parallel, not-Sprint-002-scope action item

Now that Vaishali is back, the still-outstanding review of the INV-02
amendment (`docs/Claude.md` v2.8) — currently blocking ENH-009 (Pass 3 AI
matching) — should get resolved sometime during this sprint. It doesn't have to
happen before SPRINT-002 starts and isn't part of this sprint's scope, but
flagging it here so it doesn't quietly stay "provisional" indefinitely.

---

## Definition of done for this sprint

- [ ] Both engineers' briefs (ENH-002, ENH-010, ENH-011, ENH-013, ENH-014) have
      passed Prompt 1 and are Signed Off
- [ ] Prompt 2 collision-surface analysis complete across all five
- [ ] `SPRINT-002_MANIFEST.md` committed (all its own checklist items met —
      see the SPRINT-001 template for the full list)
- [ ] ENH-014's dependency on ENH-002 resolved one way or the other, not left
      ambiguous
- [ ] Watchpoints above checked, not just assumed clean
- [ ] Sprint Integration Check run on ENH-002 + ENH-011 and ENH-002 + ENH-014
      together
- [ ] `enhancements/REGISTRY.md` updated: all five moved from IN BACKLOG to
      COMPLETE (or carried over, honestly, if something doesn't finish)
