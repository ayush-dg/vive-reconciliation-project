# ENH-010_BRIEF.md

**Enhancement ID:** ENH-010
**Title:** Access Control Hardening
**Author:** TBD
**Date:** 2026-08-11
**Status:** [x] Draft | [ ] AI Review Complete | [ ] Signed Off

> **Backlog stub.** Captured now so intent/dependency/rule-conflict notes from the
> initial backlog review aren't lost. One touch point below was confirmed against
> live code on 2026-08-11 (not just described) — the rest await Prompt 1.

---

## Enhancement Intent

Proper logins/permissions for reviewers, and removal of an old backdoor password.

---

## Known Touch Points

**Confirmed via direct code trace, 2026-08-11:**
`web/routers/auth.py:21-23,37` — `FALLBACK_EMAIL`/`FALLBACK_PASSWORD`
(`"admin@vive.com"` / `"Vive@2026"`) is a real, live hardcoded credential, checked
in `_authenticate()` whenever the database lookup fails or doesn't match. The
file's own docstring (lines 6-9) already flags this as deliberate-but-temporary:
kept from Phase 3, to be removed "once database-backed users are confirmed
working end to end." This enhancement is that removal.

---

## Known Dependencies

None flagged at initial backlog review.

---

## Flagged Rule Conflict — needs an explicit decision, not just a build task

The phrase "permissions for reviewers" reads like role-based access (Admin vs.
Reviewer tiers). **`RULES.md` RULE-08 is a deliberate, documented decision that no
such separation exists** — "everyone using the dashboard does the same job today...
per-user logins exist so `resolved_by`/`disposed_by` mean something real, not to
gate access by role." If this enhancement is scoped to (a) removing the hardcoded
fallback and (b) hardening login itself (rate limiting, session hardening) —
it fits inside current rules as-is. If it's scoped to add actual role tiers, that
requires first amending RULE-08 — the same governance weight as the INV-02
amendment blocking ENH-009 — not something to build past silently. **Confirm scope
at Prompt 1 before assuming either reading.**

---

## Known Constraints

Until RULE-08 is explicitly amended, no Admin/Reviewer tier split — see above.

---

## Out of Scope

Role-based permission tiers, unless and until RULE-08 is amended (see Flagged
Rule Conflict above).

---

## Engineer Sign-Off

[ ] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**Signed:**
**Date:**
