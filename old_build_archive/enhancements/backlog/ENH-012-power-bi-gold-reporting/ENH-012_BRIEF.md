# ENH-012_BRIEF.md

**Enhancement ID:** ENH-012
**Title:** Power BI / Gold Reporting
**Author:** TBD
**Date:** 2026-08-11
**Status:** [x] Draft | [ ] AI Review Complete | [ ] Signed Off

> **Backlog stub.** Captured now so intent/dependency notes from the initial
> backlog review aren't lost. Known Touch Points are not yet researched — that
> happens at Prompt 1.

---

## Enhancement Intent

Build the reports/dashboards layer on top of the Gold tables
(`gold_matched_invoices`, `gold_exceptions`, `gold_reconciliation_summary`).

---

## Known Dependencies

None strictly blocking, but richer once **ENH-002 (Run Management Layer)** and
**ENH-008 (Audit Ledger Unification)** land — both give reporting a natural
grouping and audit trail to report against.

---

## Flagged Collision Risk

None flagged at initial backlog review.

---

## Known Constraints

**RULE-03:** dashboard KPI cards must live-query `gold_exceptions` for exception
counts — never trust the `gold_reconciliation_summary` snapshot directly. The
same live-query-not-snapshot principle should be checked against any new Power BI
measure built on Gold.

---

## Out of Scope

TBD at Prompt 1.

---

## Engineer Sign-Off

[ ] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**Signed:**
**Date:**
