**Session:** Session 2 — Document Intake
**Date:** 2026-08-27
**Engineer:** Vaishali

## Task 2.1 — Upload screen (UI)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 2

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Select a PDF and a legal entity, submit | Confirmation toast shown, stays on `/upload` — no vendor selection required | WRITTEN — 2 assertions | PASS |
| TC-2 | Submit without a file | Validation message shown | WRITTEN — 2 assertions | PASS |
| TC-3 | Uploaded-document list, freshly-registered not-yet-extracted row | Shows "Identifying…" for vendor | WRITTEN — 2 assertions | PASS |
| TC-4 (added) | Submit without a legal entity (S4) | Validation message shown | WRITTEN — 2 assertions | PASS |
| TC-5 (added) | Re-upload identical bytes (G4) | `duplicate: true`, same `document_id`, no second row | N/A (API-level test) | PASS |
| TC-6 (added) | Re-upload identical bytes under a different legal entity | `legalEntityMismatch: true`, original entity preserved, error toast (not silently applied) | N/A (API-level test) | PASS |
| TC-7 (added) | Non-PDF file, empty MIME type, non-`.pdf` name | Rejected — "PDF files only" | WRITTEN — 1 assertion | PASS |

`ui_tests/upload.spec.ts`: 7 tests, all PASS. Full suite (`npx playwright test`): 20/20 PASS, run twice for stability.

### Challenge Agent Output
Run via an independent subagent (no build-session context), evidence-only.

**Verdict:** FINDINGS — 2 items, both real defects, both fixed. Discovering and fixing them surfaced two further real bugs during the fix/test pass itself (see below) — none were silently worked around.

**Untested scenarios / Unverified assumptions (from the challenge):**
1. PDF-type validation (`file.type && file.type !== 'application/pdf' && !file.name...`) failed open — accepted any file when the browser reported an empty MIME type, regardless of filename or actual content.
2. Duplicate-hash uploads under a *different* `legalEntityId` silently discarded the new selection with no comparison, no warning, and no test coverage.
3. No test in the original diff exercised the duplicate-upload path at all (all fixtures used random bytes).

**Invariant coverage gaps:** S1 — upheld by absence of any matching-service call site anywhere in `src/` (none exists yet; Session 5 not built), not by an explicit runtime guard. Correct for this build's current state, but noted as inspection-based, not machine-asserted (matches Task 2.2's own stated verification approach for later formalization).

**Structural complexity check:** CLEAN across all new functions/components.

**Finding dispositions:**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
| 1 (PDF-type check fails open) | TEST | Rewrote the check to require a *positive* PDF signal (`file.type === 'application/pdf' \|\| name.endsWith('.pdf')`) instead of a short-circuiting negative check; added a regression test with empty `mimeType` + non-`.pdf` name | PASS |
| 2 (silent legal-entity mismatch on duplicate) | TEST | Added `legalEntityMismatch` to `RegisterResult`; UI now shows a distinct error toast ("already uploaded under a different legal entity... not applied") instead of the generic success toast; added a dedicated test | PASS |
| Untested #3 (no duplicate-path test) | TEST | Added dedicated duplicate-upload tests — see TC-5/TC-6. Discovered mid-fix that table-row-count assertions are flaky under Playwright's default parallel workers (shared SQLite file, concurrent test writes) — rewrote both to assert on the API's own `document_id`/`legalEntityMismatch` fields via `page.request` instead of UI row counts | PASS, stable across repeated full-suite runs |

**Two further defects found while fixing the above (not part of the original challenge output — surfaced by writing real assertions against the API's actual JSON shape):**

| # | Defect | Fix |
|---|--------|-----|
| 1 | React hydration mismatch: `new Date(...).toLocaleString()` with no explicit locale rendered differently server-side (Node's default locale) vs. client-side (browser's default locale) — e.g. `8/27/2026, 2:16:10 PM` vs `27/8/2026, 2:16:10 pm`. Caused console errors and a client-side re-render on every page load. | Added `formatUploadTimestamp()` with an explicit `'en-US'` locale and fixed `Intl.DateTimeFormat` options — both renders now agree. |
| 2 | `GET`/`POST /api/documents` were returning `DocumentRow` (camelCase: `documentId`, `legalEntityId`, ...) directly as JSON, but the client's `ApiDocument` type (and every test) expects snake_case (`document_id`, `legal_entity_id`, ...) matching the DB columns. Silently masked in the UI — undefined fields degraded gracefully (e.g. missing `vendorId` still displayed "Identifying…", which happened to look correct) — but broke outright once a test asserted on the actual response shape (`legal_entity_id` came back `undefined`). | Added `toApiDocument()` serializer in `documents.ts`; both route handlers now use it; `UploadForm.tsx` imports the shared `ApiDocument` type instead of redeclaring its own (which had silently drifted from the real casing). |

### Code Review
Invariant enforcement: S1 embedded verbatim in Task 2.2's CC prompt — but this diff does include a working backend endpoint (see Scope Decisions), so S1 was reviewed against the actual code, not just deferred by label. Confirmed: no matching-service code exists anywhere in this repo yet, so no call site could exist. Re-review required once Session 5 introduces matching.

### Scope Decisions
- **This diff includes a full working registration endpoint** (`src/lib/documents.ts`, `POST /api/documents`) even though Task 2.2 nominally owns "document registration endpoint" in EXECUTION_PLAN.md. Task 2.1's own test cases require actually submitting and observing a confirmation toast, which needs a working endpoint. Task 2.2 (next task) does its own dedicated verification pass — its own test script, explicit S1/G4 code review — against this same code rather than rebuilding it from scratch.
- **Legal Entity dropdown** is a hardcoded placeholder list (`src/lib/legalEntities.ts`) — no canonical list exists anywhere in the signed-off docs; UI_SURFACE.md itself flags this field's provenance as an open gap, and Task 2.1's own description says to flag it for revisiting, not resolve it.
- **SQLite-only** (`assertSqliteMode()` throws on Fabric mode) — consistent with every data-access module built so far; Fabric required starting Session 4.
- **Local filesystem storage** (`.data/uploads/<hash>.pdf`) — env-driven (`UPLOADS_DIR`), same pattern as `db.ts`'s SQLite/Fabric fallback.
- **Route Handler, not a Server Action**, for the upload endpoint — avoids Next's default Server Action body-size limit (1MB) given the Upload screen's stated "up to 50 MB" file-size allowance.

### BCE Impact
No BCE artifact impact — `discovery/` is empty pre-Phase 8.

### Verification Verdict
[x] All planned cases passed
[x] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[x] All FINDINGS dispositioned
[x] Pre-commit declaration recorded
[x] Code review complete (if invariant-touching)
[x] Scope decisions documented

**Status:** PASS

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
