# ENH-007_BRIEF.md

**Enhancement ID:** ENH-007
**Title:** Match Confidence Score
**Author:** Ayush Kumar Sinha
**Date:** 2026-07-24
**Status:** [x] Draft | [ ] AI Review Complete | [ ] Signed Off

> **Held — not part of Sprint 1's first task group** (Blob Storage, Event Grid,
> batch_id only). This brief is a content stub for later — captured now so the
> constraint and scope decisions aren't lost, not submitted to the brief review
> gate yet. Do not include in Sprint Manifest collision surface analysis until
> the engineer explicitly moves it forward.

---

## Enhancement Intent

Currently the system tracks one confidence value — how well the AI read the text
off the PDF (extraction confidence, already fixed separately). This enhancement
adds a second, separate confidence value: how sure the matching engine is that a
given match is actually correct, since a perfectly-read line can still produce a
shaky match (e.g. a Level 2 RO+amount match near the edge of tolerance is less
certain than an exact Level 1 match). This is a new field, not a replacement for
the existing extraction confidence.

---

## Known Touch Points

| Touch Point | BCE Artifact | Entry |
|---|---|---|
| `src/matching/engine.py` — `classify_match()` | ID_REGISTRY.md / MODULE_CONTRACTS.md | M-036 (matching engine) — already knows match level and amount delta, which this new score derives from |
| `gold_matched_invoices` (schema table) | TOPOLOGY.md (Bronze/Silver/Gold layering) | Gold-layer table — not itself a registered M-NNN module |
| `web/routers/exceptions.py` + templates (possible, future) | ID_REGISTRY.md / MODULE_CONTRACTS.md | M-003 (exceptions router) — only if this score needs to surface in the UI for Step 10's bulk-approve feature later; not confirmed |

---

## Known Constraints

| Constraint | Type | Notes |
|---|---|---|
| Must be computed deterministically (rule-based on match level + amount delta), never via an AI call | MANDATORY | Preserves IC-3/INV-02 — matching stays 100% AI-free |

---

## Out of Scope

Does not touch or modify the extraction-confidence pipeline (Claude Sonnet's
`line_confidence`, already fixed). These are two distinct, unrelated confidence
values and must not be conflated.

---

## Engineer Sign-Off

[ ] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**Signed:**
**Date:**
