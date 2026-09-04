# DRIFT-001_BRIEF.md — S7 Drift

**DRIFT ID:** DRIFT-001
**Invariant ID:** S7
**Detected:** 2026-09-03
**Sprint detected in:** SPRINT-001
**Status:** [ ] Pending Acknowledgement | [ ] SPRINT-MANDATORY | [ ] DEFERRED | [x] DISMISSED

---

## Invariant Statement

**S7 — Extraction attempts are bounded (demoted from G3)**

**Invariant (amended 2026-08-26):** A document receives at most two extraction attempts
before being flagged `OCR_LOW_CONFIDENCE`. "Failure" here means structural/arithmetic
validation failure (per amended G2) — a low-confidence-but-structurally-valid row no
longer counts as a failure that consumes a retry, since confidence is no longer a gate.

**Violation:** A document is repeatedly submitted for extraction beyond the retry bound.

(Full text: `docs/INVARIANTS.md` lines 337–361.)

---

## Harness Failure

**Severity:** WARNING
**Assertion command:** `./scripts/test_bounded_retry.sh`
**Expected outcome:** `scripts/test_bounded_retry.sh` exits 0 (per `verification/HARNESS.sh` lines 140–145).
**Actual output:**
```
FAIL | S7 | WARNING | ./scripts/test_bounded_retry.sh |
PASS: TC-1: exactly 2 attempt rows total (seeded 1 + this run's 1)
PASS: TC-1: second attempt is attempt_no=2
FAIL: TC-1: document proceeds to matching-eligible (Processing badge, not Failed/Retrying)
PASS: TC-1: a silver.statement_line row was produced on the successful 2nd attempt
PASS: TC-2 through TC-4: all sub-checks PASS
1 test case(s) FAILED.
```

---

## System Impact Analysis

**Proposed fix:**
No application code change. `discovery/INVARIANT_CATALOGUE.md`'s S7 entry (STAGE-2-UPDATE,
2026-09-02) already root-caused this exact failure: `scripts/test_bounded_retry.mjs:58`
(the script `test_bounded_retry.sh` wraps) asserts a pre-2026-08-31 expected badge value.
`src/lib/documentStatus.ts:155-158` was deliberately changed 2026-08-31 (engineer
direction) to return a distinct `'Extracted'` badge for the failed-then-succeeded retry
case, specifically to disambiguate it from `'Processing'` — the code is correct, the test
literal is stale. Fix is to update the test's expected-value assertion at line 58 to match
the current, intentional `'Extracted'` badge behavior.

**Affected modules:**
M-012 (`documentStatus.ts`) — display-only, computes the badge; enforces nothing.
M-022 (`extractionPipeline.ts`) — owning module, the actual `MAX_ATTEMPTS = 2` numeric
bound; confirmed intact and independently verified (`INVARIANT_CATALOGUE.md` S7 entry).
M-015 (`extraction.ts`) — secondary/incidental, G5 lock behavior.

**Consequences if unaddressed:**
None to system behavior — the real 2-attempt bound (M-022) is independently confirmed
enforced, and `VERIFICATION_CHECKLIST.md` was already corrected 2026-09-02 to reflect this
as a false positive. The only cost of leaving `test_bounded_retry.sh` unfixed is a
recurring false WARNING at every future `HARNESS.sh` run — alert-fatigue risk that could
mask a genuine future S7 regression under the same "expected, ignore it" reflex.

---

## Sprint Disposition

[ ] SPRINT-MANDATORY — addressed before any ENH work in this sprint
    CRITICAL items are SPRINT-MANDATORY by default.

[ ] DEFERRED — target sprint: SPRINT-NNN
    Rationale: [Sprint Lead — why this can wait. Mandatory field.]
    Valid only for WARNING severity. CRITICAL requires explicit override below.

[x] DISMISSED — assertion is stale; harness update task created
    Reason: `documentStatus.ts:155-158` was intentionally changed 2026-08-31 (engineer
    direction) to return a distinct `'Extracted'` badge for the failed-then-succeeded
    retry case, disambiguating it from `'Processing'`. `scripts/test_bounded_retry.mjs:58`
    still asserts the pre-2026-08-31 expected value and was never updated to match. The
    real S7 enforcement point (`extractionPipeline.ts`'s `MAX_ATTEMPTS` bound, M-022) is
    unaffected and independently confirmed intact — this is a test-literal staleness
    issue, not an invariant violation. Root-caused in `discovery/INVARIANT_CATALOGUE.md`'s
    S7 entry, 2026-09-02; `VERIFICATION_CHECKLIST.md` already corrected to match.
    Sprint task created: Update `scripts/test_bounded_retry.mjs:58` (and its
    `test_bounded_retry.sh` wrapper) to assert the current `'Extracted'` badge value
    instead of the stale pre-2026-08-31 literal, then re-run `verification/HARNESS.sh` to
    confirm S7 PASS. Recorded in `SPRINT-001_LOG.md` Event Log.

**CRITICAL override (complete only if CRITICAL is being DEFERRED):**
Override rationale: N/A — this item is WARNING severity, not CRITICAL.
Sprint Lead: — —

---

## Sprint Lead Sign-Off

[x] Harness failure output reviewed
[x] System impact assessment reviewed — amended where operational context was missing
[x] Disposition decision recorded
[ ] If SPRINT-MANDATORY: brief submitted for inclusion in sprint manifest analysis — N/A, not SPRINT-MANDATORY

**Signed:** Vaishali
**Date:** 2026-09-03
