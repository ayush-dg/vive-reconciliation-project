# ENH-009_BRIEF.md

**Enhancement ID:** ENH-009
**Title:** Pass 3 AI-Assisted Matching
**Author:** TBD
**Date:** 2026-08-11
**Status:** [x] Draft | [ ] AI Review Complete | [ ] Signed Off — **BLOCKED, do not
schedule into a sprint yet.**

> **Backlog stub, blocked.** This is not an ordinary "independent, build whenever"
> backlog item. The invariant that permits this work — INV-02's Pass 3 exception
> (`docs/Claude.md` v2.8) — was amended unilaterally by Ayush Kumar Sinha on
> 2026-08-06 while the Sprint Lead was on leave, and is explicitly recorded there
> as **"provisional... not yet a joint or fully methodology-compliant sign-off."**
> Get the Sprint Lead's confirmation (or revision) of that amendment before this
> item enters any sprint. Building against an unratified invariant risks having to
> rework or revert the feature if her review changes the constraints.

---

## Enhancement Intent

Build the actual AI-assisted matching feature for Pass 3 disambiguation, per the
target architecture's D4/D5 design (`docs/target-architecture/
VIVE_Statement_Reconciliation_Architecture_v3_1.md`) — the feature the INV-02
amendment was written to permit. No Pass 3 code exists yet.

---

## Known Dependencies

Governance dependency, not a build dependency: blocked on Sprint Lead review of
the INV-02 amendment (see notice above). No dependency on other backlog items in
this round.

---

## Flagged Collision Risk

None flagged — but note this touches `src/matching/engine.py`, which RULE-03
otherwise documents as 100% AI-free. Any implementation must stay within the
narrow exception INV-02 carves out, not expand it.

---

## Known Constraints

The five INV-02 sub-constraints, individually non-negotiable per that invariant:
Pass 3 consults Claude Sonnet 4.6 only on the residual left after Passes 1-2; the
candidate set is SQL-retrieved and capped at ≤10 records; output must pass schema
validation before use — free-form AI text never directly drives a match or
accounting action; `review_required` must always be `true` (Pass 3 never
auto-approves, at any confidence); confidence is hard-capped at 0.85.

---

## Out of Scope

Any change to Pass 1/Pass 2 determinism (RULE-03) — those remain 100% AI-free
regardless of how this amendment resolves.

---

## Engineer Sign-Off

[ ] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**Signed:**
**Date:**
