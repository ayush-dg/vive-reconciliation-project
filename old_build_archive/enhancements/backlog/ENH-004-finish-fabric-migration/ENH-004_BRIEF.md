# ENH-004_BRIEF.md

**Enhancement ID:** ENH-004
**Title:** Finish the Fabric Migration
**Author:** TBD
**Date:** 2026-08-11
**Status:** [x] Draft | [ ] AI Review Complete | [ ] Signed Off

> **Backlog stub.** Captured now so intent/dependency/collision notes from the
> initial backlog review aren't lost. Known Touch Points are not yet researched
> beyond what's already documented in `docs/ARCHITECTURE.md` §8/§9 — full research
> happens at Prompt 1.

---

## Enhancement Intent

Complete the Fabric migration for the remaining tables `docs/Claude.md` v2.9
tracks as still open: the four unmigrated Recon tables (`jobs`,
`exception_dispositions`, `users`, `ai_audit_log`) and all of Bronze/Silver/Gold.
The three-table cut-over (`extraction_cache`, `document_intake_log`,
`validation_document_review_queue` → real SQL database in Fabric) is already done
— this enhancement is the rest of `docs/ARCHITECTURE.md` §9's target state.

---

## Known Dependencies

Independent per initial backlog review — does not require any other item in this
round to land first.

---

## Flagged Collision Risk

**ENH-002 (Run Management Layer)** and **ENH-008 (Audit Ledger Unification)** —
both flagged as possibly touching the same file/table. `ai_audit_log` is one of
the four tables this migration moves, and ENH-008 is unifying audit logs; ENH-002
may add a new Recon-classified table that lands wherever this migration is
currently routing things. Needs Prompt 2 collision-surface resolution — explicit
ownership/sequencing — before any two of these three are built concurrently.

---

## Known Constraints

**docs/Claude.md RULE-6:** any change to `src/lakehouse/connection.py` for this
migration must be scoped exactly to ARCHITECTURE.md §9's table-group routing —
don't fold in unrelated fixes, and don't silently resolve any transaction that
spans two table groups (e.g. a Bronze write + a Recon write in the same
transaction) — flag it and confirm with the engineer instead.

---

## Out of Scope

Live NetSuite integration remains untouched (RULE-06) — this migration doesn't
change the mock/real ERP split, only where the tables physically live.

---

## Engineer Sign-Off

[ ] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**Signed:**
**Date:**
