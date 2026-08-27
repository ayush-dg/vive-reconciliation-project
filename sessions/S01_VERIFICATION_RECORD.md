**Session:** Session 1 — Scaffolding + Auth + DB Schema Foundation
**Date:** 2026-08-27
**Engineer:** Vaishali

## Task 1.1 — Repository scaffolding + Playwright setup

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 1

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | `npx playwright --version` | Returns a version string | N/A | |
| TC-2 | Missing `FABRIC_SQL_ENDPOINT` env var | Falls back to local SQLite without crashing | N/A | |

### Challenge Agent Output
[Written by the build agent. Populated during task execution.]

**Verdict:**

**Untested scenarios:**

**Unverified assumptions:**

**Invariant coverage gaps:**

**Scope boundary observations:**

**Finding dispositions (FINDINGS verdict only):**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
|           |             |                              |             |

### Code Review
Not invariant-touching — pure scaffolding. GLOBAL invariants apply implicitly to all subsequent tasks, not to this one directly.

### Scope Decisions
[Recorded during task execution.]

### BCE Impact
No BCE artifact impact — `discovery/` is empty pre-Phase 8.

### Verification Verdict
[ ] All planned cases passed
[ ] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[ ] All FINDINGS dispositioned — ACCEPT with rationale or TEST with result
[ ] Pre-commit declaration recorded
[ ] Code review complete (if invariant-touching)
[ ] Scope decisions documented

**Status:**

---

## Task 1.2 — Database schema: `extracted`, `silver`, `recon` foundation tables

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 1

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Insert `extracted.document` row with all required fields | Succeeds | N/A | |
| TC-2 | Insert `extracted.document` row with `legal_entity_id = NULL` | Rejected by the database — INVARIANT TOUCH: S4 | N/A | |
| TC-3 | Vendor registry lookup for a known `vendor_id` | Resolves to the correct `extracted.stmt_<vendor_slug>` table name | N/A | |
| TC-4 | Insert `recon.exception` row with an unrecognized `category` value | Rejected — INVARIANT TOUCH: S5 | N/A | |
| TC-5 | UPDATE on an existing `extracted.extraction_attempt` row, or any `extracted.stmt_*` row | Fails or is blocked by trigger — INVARIANT TOUCH: G1 | N/A | |
| TC-6 | Run migration scripts against both SQLite (local dev) and a real Fabric SQL database connection | Clean run on both, no dialect-specific syntax that only works on one | N/A | |

### Challenge Agent Output
[Written by the build agent. Populated during task execution.]

**Verdict:**

**Untested scenarios:**

**Unverified assumptions:**

**Invariant coverage gaps:**

**Scope boundary observations:**

**Finding dispositions (FINDINGS verdict only):**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
|           |             |                              |             |

### Code Review
[Required — this task touches S4, S5, S10, S11, G1. For each: confirm the invariant condition
is actually enforced in the schema/migration, no code path bypasses it, enforcement is in the
right place (schema-level, not just application-layer convention), and future additions cannot
bypass it without explicitly removing the check.]

| Invariant | Enforcement point to check | Result |
|---|---|---|
| S4 | NOT NULL constraint on `extracted.document.legal_entity_id` | |
| S5 | CHECK constraint on `recon.exception.category` against fixed enum | |
| S10 | `extracted.extraction_attempt` / `extracted.stmt_*` have no application-layer UPDATE path | |
| S11 | `silver.statement_line.amount` has no application-layer UPDATE path | |
| G1 | FK `extraction_attempt.document_id` → `extracted.document`; append-only enforced (trigger or documented discipline) on every `extracted` schema table | |

### Scope Decisions
[Recorded during task execution — e.g. PK generation strategy chosen for SQLite/Fabric T-SQL portability.]

### BCE Impact
No BCE artifact impact — `discovery/` is empty pre-Phase 8.

### Verification Verdict
[ ] All planned cases passed
[ ] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[ ] All FINDINGS dispositioned — ACCEPT with rationale or TEST with result
[ ] Pre-commit declaration recorded
[ ] Code review complete (if invariant-touching)
[ ] Scope decisions documented

**Status:**

---

## Task 1.3 — Authentication (Sign In screen)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 1

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Valid credentials submitted | Redirect to `/home` | | |
| TC-2 | Invalid credentials submitted | Inline error shown, no redirect | | |
| TC-3 | Session idle for 30+ minutes | Redirect to `/login` on next action | | |

### Challenge Agent Output
[Written by the build agent. Populated during task execution.]

**Verdict:**

**Untested scenarios:**

**Unverified assumptions:**

**Invariant coverage gaps:**

**Scope boundary observations:**

**Finding dispositions (FINDINGS verdict only):**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
|           |             |                              |             |

### Code Review
Not invariant-touching per EXECUTION_PLAN.md ("None task-scoped directly — authentication is
infrastructure"). OD5's multi-user resolution (multiple named users share one role) is a design
constraint reflected in the CC prompt, not a GLOBAL/TASK-SCOPED invariant.

### Scope Decisions
[Recorded during task execution.]

### BCE Impact
No BCE artifact impact — `discovery/` is empty pre-Phase 8.

### Verification Verdict
[ ] All planned cases passed
[ ] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[ ] All FINDINGS dispositioned — ACCEPT with rationale or TEST with result
[ ] Pre-commit declaration recorded
[ ] Code review complete (if invariant-touching)
[ ] Scope decisions documented

**Status:**

---

## Task 1.4 — Global elements (sidebar nav, logout, error boundary, loading, toast)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 1

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Sidebar renders | All three active nav items (Home, Upload, Exceptions) present, logout clickable | | |
| TC-2 | Click a disabled Admin nav item | No navigation occurs | | |
| TC-3 | Simulated API error triggered | Inline message with Retry action shown | | |

### Challenge Agent Output
[Written by the build agent. Populated during task execution.]

**Verdict:**

**Untested scenarios:**

**Unverified assumptions:**

**Invariant coverage gaps:**

**Scope boundary observations:**

**Finding dispositions (FINDINGS verdict only):**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
|           |             |                              |             |

### Code Review
Not invariant-touching.

### Scope Decisions
[Recorded during task execution.]

### BCE Impact
No BCE artifact impact — `discovery/` is empty pre-Phase 8.

### Verification Verdict
[ ] All planned cases passed
[ ] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[ ] All FINDINGS dispositioned — ACCEPT with rationale or TEST with result
[ ] Pre-commit declaration recorded
[ ] Code review complete (if invariant-touching)
[ ] Scope decisions documented

**Status:**
