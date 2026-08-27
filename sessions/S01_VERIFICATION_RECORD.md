**Session:** Session 1 — Scaffolding + Auth + DB Schema Foundation
**Date:** 2026-08-27
**Engineer:** Vaishali

## Task 1.1 — Repository scaffolding + Playwright setup

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 1

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | `npx playwright --version` | Returns a version string | N/A | PASS — `Version 1.62.1` |
| TC-2 | Missing `FABRIC_SQL_ENDPOINT` env var | Falls back to local SQLite without crashing | N/A | PASS — `npm run test:db-fallback` (scripts/verify_db_fallback.mjs): `{"mode":"sqlite","ok":true}` |

### Challenge Agent Output
Run via an independent subagent (no build-session context), evidence-only, per `tools/challenge.sh`'s prompt contract.

**Verdict:** FINDINGS — 6 items (all dispositioned below; commit proceeded after fixes/rationale, not before).

**Untested scenarios:**
1. `db.ts`'s connection logic had no automated/reproducible test — the task's own specified failure-case test was verified only ad hoc.
2. Root route (`/`) redirected to `/login`, which didn't exist in this diff — confirmed 404 via live dev server.
3. `db.ts` was not called from anywhere in the app — no boot hook, no health route.

**Unverified assumptions:**
1. `getSqlitePath()` resolves against `process.cwd()` with no validation — confirmed to silently open a different DB file when launched from an unexpected working directory.
2. Committed `next-env.d.ts` diverges from the state `npm run dev` (the exact command Playwright's `webServer` invokes) regenerates on first run.
3. Module-level singletons (`sqliteInstance`, `fabricPoolPromise`) have no invalidation path if the driving env var changes mid-process.

**Invariant coverage gaps:** NONE — Task 1.1 is explicitly "None task-scoped (pure scaffolding)"; no schema/data created by this diff.

**Scope boundary observations:** None raised — all findings were fixable within Task 1.1's own file set (`src/lib/db.ts`, `src/app/page.tsx`, plus one new health route and one new verification script, both within Claude.md's `/src/**` and `/scripts/**` scope).

**Structural complexity check (all six functions):** CLEAN — single stateable purpose each, no conditional nesting beyond one level.

**Finding dispositions:**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
| 1 (db.ts untested) | TEST | Added `scripts/verify_db_fallback.mjs` + `npm run test:db-fallback` — reproducible, non-ad-hoc check of the exact Task 1.1 failure case | PASS — see TC-2 above |
| 2 (root route 404s) | TEST | Removed the premature `redirect('/login')` (Task 1.3 owns wiring root -> `/login` once it exists); replaced with a neutral scaffold placeholder | PASS — `npm run build` succeeds, `/` renders statically, no dead redirect |
| 3 (db.ts unreachable) | TEST | Added `src/app/api/health/route.ts` — a minimal `GET` handler calling `pingDb()`, giving the connection module a real request path | PASS — appears as `ƒ /api/health` in `next build` route output |
| 4 (cwd-relative SQLite path) | ACCEPT | `process.cwd()` is the app root at runtime for both `next dev`/`next start` locally and standard App Service deployments — documented in a code comment; not changed, since anchoring elsewhere would fight the deployment convention rather than follow it | N/A — no test required |
| 5 (`next-env.d.ts` drift) | ACCEPT | Standard Next.js framework self-maintenance behaviour (regenerates on first `next dev`/`next build`), identical across every Next.js 13+ project — not a defect introduced by this task | N/A — no test required |
| 6 (no singleton invalidation) | ACCEPT | Env-var-driven config is read once at process start per standard 12-factor/App Service convention; runtime env-var mutation without a process restart is out of scope for this system | N/A — no test required |

### Code Review
Not invariant-touching — pure scaffolding. GLOBAL invariants apply implicitly to all subsequent tasks, not to this one directly.

### Scope Decisions
- Framework: Next.js 16 (App Router) + TypeScript, chosen over the originally-installed 14.2.5 after `npm audit` surfaced multiple HIGH-severity advisories against 14.2.5 with no fix short of a major bump — greenfield project, zero cost to start on a patched major version instead of pinning a vulnerable one. React bumped 18 -> 19 to match.
- Local dev DB driver: `better-sqlite3` (installs via prebuilt binary on this platform, no native toolchain required). Fabric path: `mssql` (untested — no live Fabric endpoint available; required starting Session 4 per EXECUTION_PLAN.md).
- Added `src/app/api/health/route.ts` and `scripts/verify_db_fallback.mjs` beyond the CC prompt's literal text, in direct response to Challenge Agent findings 1 and 3 — both stay inside Task 1.1's own stated deliverable (the DB connection module) and inside Claude.md's `/src/**` and `/scripts/**` scope, not scope creep into a later task.

### BCE Impact
No BCE artifact impact — `discovery/` is empty pre-Phase 8.

### Verification Verdict
[x] All planned cases passed
[x] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[x] All FINDINGS dispositioned — ACCEPT with rationale or TEST with result
[x] Pre-commit declaration recorded
[x] Code review complete (if invariant-touching) — N/A, not invariant-touching
[x] Scope decisions documented

**Status:** PASS

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
