# ENH-004_BRIEF.md

**Enhancement ID:** ENH-004
**Title:** Vendor-specific invoice matching logic (investigation-first)
**Author:** Vaishali
**Date:** 2026-09-03
**Status:** [x] Draft — NOT READY for brief review gate, see note below

---

## Enhancement Intent

**This brief's actual deliverable is an investigation, not a build scope — recorded to
hold the ENH-004 slot in the backlog, not because acceptance criteria exist yet.**
`deterministicMatching.ts` (M-026) currently uses one generic algorithm to match every
vendor's normalized invoice reference against NetSuite's `tranid` field. Unlike
extraction — where 9 vendors were confirmed, per-vendor, to fail the generic path before
any deterministic parser was built (Session 8/9) — there is no existing evidence in any
BCE artifact (`MODULE_CONTRACTS.md`, `RISK_REGISTER.md`) that the generic matching
algorithm actually fails for any real vendor. Writing acceptance criteria now would mean
guessing at both the problem and the fix.

**The actual first deliverable of this enhancement is an investigation:** run current
matching against real statements for each known vendor and measure the match/exception
split per vendor, specifically the `not_posted` category rate (the signal for invoice-ref
format mismatch, as distinct from a genuine amount discrepancy). If real per-vendor
mismatches are found, this brief gets rewritten with concrete acceptance criteria (which
vendors, what pattern, what fix) at that point. If the generic path already works across
all vendors, this item closes without ever becoming a build task — same discipline that
produced the 9 extraction parsers, applied here before assuming a parallel need exists.

---

## Known Touch Points

| Touch Point | BCE Artifact | Entry |
|---|---|---|
| Deterministic matching (the algorithm under investigation) | MODULE_CONTRACTS.md | M-026 (deterministicMatching.ts) |
| NetSuite bill/credit reference data (external, read-only) | INTEGRATION_CONTRACTS.md | IP-003 |

(Full Known Touch Points cannot be written until the investigation identifies which, if
any, vendors/modules actually need a fix.)

---

## Known Constraints

| Constraint | Type | Notes |
|---|---|---|
| No acceptance criteria exist yet — investigation must run first | MANDATORY | See Enhancement Intent. This brief should not proceed to a brief review gate as a build-scoped enhancement until the investigation produces real findings. |
| If real vendor-specific logic is needed, follow the extraction precedent | OPTIONAL | Build vendor-specific matching only where evidence shows the generic path fails for that specific vendor — do not generalize a fix across vendors that already match correctly, mirroring how Session 9's 9 extraction parsers were each kept independent with their own documented reconciliation rule. |

---

## Out of Scope

- Any code change, until the investigation determines one is actually needed.
- Extraction logic (already vendor-specific where evidenced, per Session 8/9) — this
  enhancement is about the matching stage only, not extraction.

---

## Engineer Sign-Off
[ ] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**NOT SIGNED — this brief should not be signed off as a build-scoped enhancement until
the investigation above has run and produced real findings.**

**Signed:** _________________________
**Date:** ___________
