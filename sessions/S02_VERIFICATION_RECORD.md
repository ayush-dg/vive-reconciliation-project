**Session:** Session 2 — Document Intake
**Date:** 2026-08-27
**Engineer:** Vaishali

## Task 2.1 — Upload screen (UI)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 2

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Select a PDF and a legal entity, submit | Confirmation toast shown, stays on `/upload` — no vendor selection required | | |
| TC-2 | Submit without a file | Validation message shown | | |
| TC-3 | Uploaded-document list, freshly-registered not-yet-extracted row | Shows "Identifying…" for vendor | | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
Invariant enforcement: S1 embedded verbatim in this task's CC prompt for Task 2.2 — this task builds UI only, not the backend trigger logic.

### Scope Decisions
[Recorded during task execution.]

### BCE Impact
No BCE artifact impact — `discovery/` is empty pre-Phase 8.

### Verification Verdict
[ ] All planned cases passed
[ ] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[ ] All FINDINGS dispositioned
[ ] Pre-commit declaration recorded
[ ] Code review complete (if invariant-touching)
[ ] Scope decisions documented

**Status:**

---

## Task 2.2 — Document registration + content-hash dedup

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 2

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Upload a genuinely new document (new hash) | Registers cleanly, `vendor_id`/`statement_period` NULL, no prior version link | N/A | |
| TC-2 | Re-upload the identical file (same hash) | Rejected/ignored, no new row — INVARIANT TOUCH: G4 | N/A | |
| TC-3 | Registration endpoint call | Does not call the matching service — INVARIANT TOUCH: S1 | N/A | |
| TC-4 | Registration endpoint code path | Does not perform vendor/period version-chaining (that's Task 3.1) | N/A | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
[Required — S1, G4.]

| Invariant | Enforcement point to check | Result |
|---|---|---|
| S1 | Registration endpoint never calls matching service, sync or async | |
| G4 | `content_sha256` UNIQUE constraint (Task 1.2) enforces idempotency at write time | |

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

## Task 2.3 — Home's status badge wiring

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 2

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Document with zero extraction attempts | Status "Processing" | N/A | |
| TC-2 | Document with one failed attempt | Status "Retrying (1/2)" | N/A | |
| TC-3 | Document with two failed attempts | Status "Failed — see Exceptions" | N/A | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
Invariant enforcement: None new (relies on G1/S7's underlying data — no extraction service exists yet in Session 2, so this task's own tests exercise the computation against directly-inserted `extraction_attempt` rows, not a live pipeline).

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

## Task 2.4 — Extract action (UI trigger + endpoint)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 2

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Click Extract on a registered document | Status transitions to "Processing", triggers extraction service | | |
| TC-2 | Uploading a document (Task 2.2) | Does not itself invoke extraction — status remains pre-Processing until Extract clicked | | |
| TC-3 | Extract button state once extraction has started | Not shown / disabled | | |
| TC-4 (G5) | Trigger Extract twice in rapid succession on same `document_id` | Exactly one extraction attempt started; second rejected | | |

### Challenge Agent Output
[Populated during task execution.]

### Code Review
[Required — D-I, G5.]

| Invariant | Enforcement point to check | Result |
|---|---|---|
| D-I | Extract endpoint not reachable automatically from the registration code path (Task 2.2) | |
| G5 | Atomic ownership acquisition (`UPDATE ... WHERE status != 'Processing'` guard or row lock) before invoking extraction | |

### Scope Decisions
[Recorded during task execution — e.g. how "Session 3's extraction service" is stubbed, since Session 3 doesn't exist yet.]

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
