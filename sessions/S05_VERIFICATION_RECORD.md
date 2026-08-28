**Session:** Session 5 — Matching Service
**Date:** 2026-08-28
**Engineer:** Vaishali

## Task 5.1 — Matching invocation (manual + scheduled)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 5

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Manual API trigger | Executes matching against currently eligible StatementLines | N/A | |
| TC-2 | Scheduled batch job | Executes matching on its configured cadence | N/A | |
| TC-3 | Uploading a document (Task 2.2's endpoint) | Does not itself invoke matching — INVARIANT TOUCH: S1 | N/A | |
| TC-4 | Manual trigger and scheduled batch invoked concurrently against overlapping eligible documents | Each document matched exactly once, never twice — INVARIANT TOUCH: G5 | N/A | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
[Required — S1, G5.]

### Scope Decisions
[Recorded during task execution.]

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[ ] All planned cases passed
[ ] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[ ] All FINDINGS dispositioned
[ ] Pre-commit declaration recorded
[ ] Code review complete (if invariant-touching)
[ ] Scope decisions documented

**Status:**

---

## Task 5.2 — Deterministic matching (SQL-based)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 5

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | StatementLine with a matching NetSuite Bill document number | Produces a Match record, with `reference_run_id`/`reference_extracted_at`/`reference_source_system` populated from the specific NetSuite row matched | N/A | |
| TC-2 | StatementLine with no corresponding NetSuite record | Produces an Exception (category e.g. `NOT_POSTED`), with the same 3 reference columns populated | N/A | |
| TC-3 | Attempt to write a Match with any of the 3 reference columns null | Rejected — INVARIANT TOUCH: S8 (amended) | N/A | |
| TC-4 | Matching logic execution | Never makes a live NetSuite/CCC API call | N/A | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
Invariant enforcement: S8 (amended).

### Scope Decisions
[Recorded during task execution.]

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[ ] All planned cases passed
[ ] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[ ] All FINDINGS dispositioned
[ ] Pre-commit declaration recorded
[ ] Code review complete (if invariant-touching)
[ ] Scope decisions documented

**Status:**

---

## Task 5.3 — AI-assisted residual matching (never auto-approves)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 5

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Residual line with CCC RO corroboration | Produces an actionable exception category with a specific suggested action, but is NOT marked as an approved match | N/A | |
| TC-2 | Any code path from this pass | No path allows directly setting a final "matched"/"reconciled" status without deterministic confirmation — INVARIANT TOUCH: AI-write-authority non-negotiable | N/A | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
Invariant enforcement: G3; AI-write-authority non-negotiable.

### Scope Decisions
[Recorded during task execution.]

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[ ] All planned cases passed
[ ] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[ ] All FINDINGS dispositioned
[ ] Pre-commit declaration recorded
[ ] Code review complete (if invariant-touching)
[ ] Scope decisions documented

**Status:**

---

## Task 5.4 — Exception category enum + schema wiring

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 5

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Every exception-producing path | Writes a valid enum category | N/A | |
| TC-2 | Attempt to write an unrecognized category string | Rejected — INVARIANT TOUCH: S5 | N/A | |
| TC-3 | Any exception created | `owner`/`aging_started_at`/`run_reference` remain NULL | N/A | |
| TC-4 | NOT_POSTED exception (Task 5.2's no-match path) | Carries non-NULL `reference_run_id`/`reference_extracted_at`/`reference_source_system` | N/A | |
| TC-5 | Arithmetic-mismatch exception (Task 3.2) | Leaves the 3 reference columns NULL — never touched reference data | N/A | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
Invariant enforcement: S5; S8 (amended).

### Scope Decisions
[Recorded during task execution.]

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[ ] All planned cases passed
[ ] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[ ] All FINDINGS dispositioned
[ ] Pre-commit declaration recorded
[ ] Code review complete (if invariant-touching)
[ ] Scope decisions documented

**Status:**
