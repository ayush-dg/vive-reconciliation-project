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
| TC-1 | Insert `extracted.document` row with all required fields | Succeeds | N/A | PASS |
| TC-2 | Insert `extracted.document` row with `legal_entity_id = NULL` | Rejected by the database — INVARIANT TOUCH: S4 | N/A | PASS — `NOT NULL constraint failed` |
| TC-3 | Vendor registry lookup for a known `vendor_id` | Resolves to the correct `extracted.stmt_<vendor_slug>` table name | N/A | PASS |
| TC-4 | Insert `recon.exception` row with an unrecognized `category` value | Rejected — INVARIANT TOUCH: S5 | N/A | PASS — `CHECK constraint failed` |
| TC-5 | UPDATE on an existing `extracted.extraction_attempt` row, or any `extracted.stmt_*` row | Fails or is blocked by trigger — INVARIANT TOUCH: G1 | N/A | PASS — both cases (TC-5, TC-5b) |
| TC-6 | Run migration scripts against both SQLite (local dev) and a real Fabric SQL database connection | Clean run on both, no dialect-specific syntax that only works on one | N/A | PARTIAL — SQLite: PASS (`npm run migrate`). Fabric: NOT RUN — no live `FABRIC_SQL_ENDPOINT` in this environment; see Known Untested Scenarios below. One deliberate, documented dialect fork exists (schema-qualified vs flattened table names — see both migration files' headers) — "no syntax rework" is satisfied at the logical-schema level, not as byte-identical SQL text. |

### Challenge Agent Output
Run via an independent subagent (no build-session context), evidence-only.

**Verdict:** FINDINGS — 1 item (SQL-injection-shaped gap in vendor slug handling) required a fix; the rest were coverage gaps addressed by extending the test script.

**Untested scenarios (from the challenge, since fixed):**
1. G1's FK-validity half (invalid `document_id` rejected) — TC-5/5b only covered the append-only half.
2. G4's UNIQUE `content_sha256` duplicate-rejection — present in schema, had zero test coverage.
3. Migration idempotency on re-run — only "applies cleanly to a fresh db" had been checked; raw `CREATE TABLE` (no `IF NOT EXISTS`) would have failed loudly on a second run via any path bypassing `_migrations` bookkeeping.
4. `provider_used` / `extraction_route` CHECK constraints — untested (only `category`'s CHECK was tested).

**Unverified assumptions (since fixed):**
1. `vendorSlug` was interpolated unvalidated, unquoted, directly into `CREATE TABLE`/`CREATE TRIGGER`/`RAISERROR` DDL text in both `vendorStmtTableDdlFabric` and `vendorStmtTableDdlSqlite`. Challenge agent empirically confirmed a crafted slug (`"x (y int); DROP TABLE extracted_document; --"`) executes as multiple statements via `better-sqlite3`'s `db.exec()`, actually dropping the table. Real risk per ARCHITECTURE.md D-L: vendor slugs can originate from Claude's document-content-based identification for unknown vendors, not only a curated list.

**Invariant coverage gaps:**
- S10 — flagged by the challenge agent as not schema-testable in principle: S10 is a write-*ordering* invariant (extraction_attempt written before validation decides pass/fail), and no validation-gate code exists yet (Task 3.2, Session 3). This task supplies the tables to write into; the ordering guarantee itself is Task 3.1/3.2's responsibility, not Task 1.2's. Noted, not a gap in this task's own deliverable.
- G1, S4, S5, S11 — all closed by the (now-extended) test script; see Code Review below.

**Scope boundary observations:** None — all fixes stayed inside this task's own file set (`src/lib/schema.ts`, `migrations/001_foundation_schema.sqlite.sql`, `scripts/test_foundation_schema.mjs`), within Claude.md's `/migrations/**`, `/src/**`, `/scripts/**` scope.

**Structural complexity check:** CLEAN across all new functions in the diff — single stateable purpose each, no conditional nesting beyond two levels.

**Finding dispositions:**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
| 1 (vendor slug DDL injection) | TEST | Added `assertValidVendorSlug()` in `src/lib/schema.ts` (allowlist regex `^[a-z][a-z0-9_]{0,62}$`), enforced at the single choke point (`vendorStmtTableBaseName`) both DDL-generating functions in `vendorSchema.ts` already route through — no bypass path | PASS — malicious slug now rejected before any DDL string is built; `extracted_document` confirmed to still exist afterward |
| Untested #1 (G1 FK-validity) | TEST | Added a check inserting an `extraction_attempt` against a nonexistent `document_id` | PASS — `FOREIGN KEY constraint failed` |
| Untested #2 (G4 UNIQUE) | TEST | Added a duplicate-`content_sha256` insert check | PASS — `UNIQUE constraint failed` |
| Untested #3 (migration idempotency) | TEST | Added `IF NOT EXISTS` to every `CREATE TABLE`/`CREATE TRIGGER` in the SQLite migration (belt-and-suspenders alongside `_migrations` bookkeeping) + a re-run check | PASS — second `runMigrations()` call: 0 applied, 1 skipped, no error |
| Untested #4 (CHECK constraints) | TEST | Added invalid-value checks for both `provider_used` and `extraction_route` | PASS — both rejected |
| S10 (write-ordering, not schema-testable) | ACCEPT | Correctly out of this task's scope per Task 1.2's own description — S10 belongs to Task 3.1's write-before-validation sequencing, not the schema itself | N/A — no test required |

### Code Review
Required — this task touches S4, S5, S10, S11, G1.

| Invariant | Enforcement point to check | Result |
|---|---|---|
| S4 | `NOT NULL` on `extracted.document.legal_entity_id` (both migration files) | CONFIRMED — schema-level, no application-layer bypass possible; TC-2 PASS |
| S5 | `CHECK` on `recon.exception.category` against fixed enum (both migration files) | CONFIRMED — schema-level; TC-4 PASS. Enum itself is an explicitly-flagged minimal placeholder (2 values), finalized at Task 5.4 |
| S10 | N/A at schema level (write-ordering invariant, not a schema constraint) — see Invariant coverage gaps above | N/A for this task; correctly deferred |
| S11 | `BEFORE UPDATE OF amount` trigger on `silver_statement_line` (SQLite) / `AFTER UPDATE` + `IF UPDATE(amount)` trigger (Fabric) | CONFIRMED for SQLite (tested). Fabric trigger syntax reviewed by inspection only — not run against a live Fabric endpoint; flagged as a Known Untested Scenario, including the open question of whether the target Fabric SQL surface supports DML triggers at all |
| G1 | FK `extraction_attempt.document_id` → `extracted.document` (tested, both valid and invalid cases) + append-only trigger on `extraction_attempt` and every `extracted.stmt_*` table (tested, both the fixed table and a generated vendor table) | CONFIRMED for SQLite. Fabric: FK/trigger syntax reviewed by inspection; not run live |

### Scope Decisions
- **PK generation strategy:** application-generated TEXT/NVARCHAR UUIDs on every table, not `IDENTITY`/`AUTOINCREMENT` — sidesteps that specific SQLite/T-SQL dialect gap entirely (same column type/constraint works unmodified in both).
- **Cross-dialect rendering:** one canonical Fabric T-SQL file (`001_foundation_schema.sql`, matches the literal Verification Command) plus one SQLite-equivalent companion file (`001_foundation_schema.sqlite.sql`), rather than one shared literal SQL text. Root cause: SQLite does not enforce foreign keys across ATTACHed databases, and G1/S11's FK and cross-schema constraints are load-bearing — an ATTACH-based single-file-per-schema rendering would have silently stopped enforcing exactly what this migration exists to enforce. Full rationale documented in both files' headers.
- **`recon.exception.category` enum:** minimal 2-value placeholder (`amount_mismatch`, `not_posted`) — the only values named anywhere in the signed-off docs as of this migration. Explicitly flagged as non-final; Task 5.4 owns the real enum. Adding values later is a new migration (CHECK constraints aren't app-layer config).
- **Per-vendor raw tables:** generator function only (`vendorSchema.ts`), no concrete vendor tables created by this migration — no vendors are known/seeded yet (data baseline = Migrated only, no Seeded component).
- **Vendor slug validation:** added in direct response to the Challenge Agent's Finding 1 (see above) — allowlist regex, not an escaping/sanitization approach, since these values become SQL identifiers (table/trigger names), not string literals.
- **Fabric path genuinely untestable here:** no live `FABRIC_SQL_ENDPOINT` in this sandbox. `migrations/001_foundation_schema.sql` was reviewed by inspection for T-SQL correctness but the literal EXECUTION_PLAN.md Verification Command (`sqlcmd -i ...`) was not run. Flagged, not silently assumed to pass — see Known Untested Scenarios below and re-run this task's Fabric-side verification once Session 4 provisions a live endpoint.

### Known Untested Scenarios (informational — not gate-blocking for Session 1-3 local dev)
- The literal EXECUTION_PLAN.md Verification Command (`sqlcmd` against `$FABRIC_SQL_ENDPOINT`) — no live Fabric endpoint available.
- Whether Fabric's specific SQL surface supports `AFTER UPDATE` DML triggers with `RAISERROR`/`ROLLBACK TRANSACTION` identically to Azure SQL DB (some Fabric SQL surfaces, e.g. Warehouse, don't support triggers at all) — requires a live connection to confirm.
- `CREATE SCHEMA extracted;` succeeding against the live `recon` Fabric SQL database (permissions, pre-existing schema conflicts).
- Cross-schema FK enforcement on the real multi-schema Fabric database (the SQLite file structurally cannot validate this, by design — see Scope Decisions).

### BCE Impact
No BCE artifact impact — `discovery/` is empty pre-Phase 8.

### Verification Verdict
[x] All planned cases passed (TC-6 PARTIAL — Fabric half not runnable in this environment, see Known Untested Scenarios; SQLite half PASS)
[x] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[x] All FINDINGS dispositioned — ACCEPT with rationale or TEST with result
[x] Pre-commit declaration recorded
[x] Code review complete (if invariant-touching)
[x] Scope decisions documented

**Status:** PASS (with one documented partial: Fabric-side of TC-6 requires a live endpoint not available in this environment)

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
