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
| TC-1 | Upload a genuinely new document (new hash), via `POST /api/documents` | Registers cleanly (201), `vendor_id`/`statement_period` NULL, no prior version link | N/A | PASS |
| TC-2 | Re-upload the identical file (same hash), same entity | Rejected/ignored (200, `duplicate:true`), no new row — INVARIANT TOUCH: G4 | N/A | PASS |
| TC-2b (added) | Re-upload the identical file (same hash), different entity | Still no new row; mismatch surfaced (`legalEntityMismatch:true`), original entity preserved — INVARIANT TOUCH: G4 | N/A | PASS |
| TC-3 | Registration endpoint call | Does not call the matching service — INVARIANT TOUCH: S1 | N/A | PASS |
| TC-4 | Registration endpoint code path | Does not perform vendor/period version-chaining (that's Task 3.1) | N/A | PASS |
| TC-5 (added) | Check-then-insert race (UNIQUE constraint hit on INSERT, not the pre-check) | Handled gracefully — no unhandled crash | N/A | PASS |

`scripts/test_document_registration.sh` (→ `.mjs`, invokes the actual `POST`/`GET` route handlers directly, not just the library function): 20/20 checks PASS. Full `ui_tests` suite re-run after this task's fix: 20/20 PASS.

### Challenge Agent Output
Run via an independent subagent (no build-session context), evidence-only.

**Verdict:** FINDINGS — 3 items, all real gaps in the verification pass itself (not new code defects, except one real robustness gap surfaced along the way — see below).

**Findings (from the challenge):**
1. The original script only called `registerDocument()` directly — never exercised `POST`/`GET /api/documents` (the actual endpoint Task 2.2 is nominally verifying). A regression introduced only in `route.ts` (wrong status code, dropped `legalEntityMismatch` field, broken form parsing) would not have been caught.
2. The `legalEntityMismatch` branch — the exact code path a prior challenge pass (Task 2.1) found and fixed as a real bug — had zero coverage in this script; the only re-upload test used the same entity both times.
3. `registerDocument()`'s `INSERT` had no handling for a `UNIQUE`-constraint violation hit directly at insert time (as opposed to caught by the pre-check read) — under a genuine check-then-insert race (plausible on Azure App Service if it ever runs multiple instances), this would surface as an unhandled crash instead of the documented graceful-duplicate response.

**Finding dispositions:**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
| 1 (route handler unexercised) | TEST | Rewrote the script to import and call `POST`/`GET` from `route.ts` directly with constructed `Request`/`FormData` objects (Route Handlers are plain functions over the standard Request/Response Web APIs — no running server needed) | PASS — all TCs now exercise the real endpoint |
| 2 (legalEntityMismatch uncovered) | TEST | Added TC-2b: re-upload identical bytes under a different `legalEntityId`, assert `legalEntityMismatch: true` and the original entity preserved | PASS |
| 3 (unhandled race on INSERT) | TEST | Added a `try/catch` around the `INSERT` in `registerDocument()` — on a `UNIQUE constraint failed` error, re-queries the winning row and returns the same graceful duplicate response the pre-check path returns, instead of throwing. Added TC-5, which confirms the error-message shape the catch's detection regex relies on (a true concurrent-process race can't be reproduced in this single-threaded, synchronous test — documented as such, not overclaimed) | PASS |

### Code Review
Required — S1, G4.

| Invariant | Enforcement point to check | Result |
|---|---|---|
| S1 | No matching-service call site anywhere in `documents.ts` or `route.ts` — confirmed by static inspection (widened regex per the challenge's Unverified Assumption 1, covering `queueMatch`/`invokeMatch`/`startReconcil` naming variants in addition to the original pattern) and by the fact that no matching-service module exists anywhere in this repo yet (Session 5 not built) | CONFIRMED — with the noted limitation that a sufficiently differently-named future call could still evade a textual scan; re-review required once Session 5 introduces matching |
| G4 | `content_sha256` UNIQUE constraint (Task 1.2, DB-level) + application-level pre-check (`findDocumentByHash`) + now a catch-based fallback for the race window between them | CONFIRMED — all three layers tested (TC-2, TC-2b, TC-5) |

### Scope Decisions
- Verification command satisfies EXECUTION_PLAN.md's literal path (`./scripts/test_document_registration.sh`) via a thin wrapper that calls `test_document_registration.mjs` through `tsx`, consistent with every other verification script in this project (TypeScript, not bash, since Session 1 — see `scripts/test_foundation_schema.mjs`).
- No code changes were needed in `documents.ts`/`route.ts` beyond the race-condition catch (Finding 3) — Task 2.1's own challenge-agent pass already found and fixed the two defects most relevant to this task's S1/G4 scope (PDF-type bypass was S1-adjacent input validation, not S1 itself; entity-mismatch was directly G4).

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed
[x] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[x] All FINDINGS dispositioned
[x] Pre-commit declaration recorded
[x] Code review complete (if invariant-touching)
[x] Scope decisions documented

**Status:** PASS

---

## Task 2.3 — Home's status badge wiring

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 2

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Document with zero extraction attempts | Status "Processing" | N/A | PASS |
| TC-2 | Document with one failed attempt | Status "Retrying (1/2)" | N/A | PASS |
| TC-3 | Document with two failed attempts | Status "Failed — see Exceptions" | N/A | PASS |
| Bonus | Attempt in progress (unvalidated) | "Processing" | N/A | PASS |
| Bonus | Validation passed, no match yet | "Processing" (not "Reconciled") | N/A | PASS |
| Bonus | `recon.match` exists | "Reconciled" (forward-compat, no live pipeline yet) | N/A | PASS |

`scripts/test_document_status_computation.sh` (→ `.mjs`): 10/10 checks PASS (3 required + 7 added, see below).

### Challenge Agent Output
Run via an independent subagent (no build-session context), evidence-only.

**Verdict:** FINDINGS — 4 items. Finding 1 is a real, significant logic bug (not just a coverage gap) — the badge computation used *lifetime* failed-attempt count instead of the *latest* attempt's outcome, so a document that failed once then succeeded on its retry stayed permanently mislabeled "Retrying (1/2)" — exactly Task 3.3's own stated happy path ("attempt 1 fails, attempt 2 succeeds → proceeds to matching-eligible").

**Findings (from the challenge):**
1. **(Real bug)** A document whose attempt 1 failed and attempt 2 succeeded reads as "Retrying (1/2)" forever — `failedCount` counted all-time failures, not whether the *latest* attempt was still unresolved.
2. The "Reconciled" branch hardcoded `attemptCount: 0` regardless of real attempt history — untested against a document with real prior attempts before its match.
3. A document with failed attempts *and* a (data-inconsistent) `recon.match` row silently reports "Reconciled" with no documented rationale for why the match takes precedence.
4. `computeDocumentStatus()` called with an unknown `document_id` silently returns a plausible-looking "Processing" result — indistinguishable from a legitimate brand-new document. (Also noted, lower-severity: no test exercised 3+ attempt rows, an S7-violating state this function doesn't write but should degrade sanely against.)

**Assessment of the Task 2.3/2.4 badge-value tension** (documented in `documentStatus.ts`'s header comment — Task 2.4's "Registered"/pre-Processing language vs. UI_SURFACE.md's fixed four-badge set with no "Registered" value): confirmed defensible by the challenge agent, no better resolution found. Not re-litigated as a finding.

**Finding dispositions:**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
| 1 (stuck-Retrying bug) | TEST | Rewrote the computation to key off the **latest** attempt's outcome: succeeded or in-progress → "Processing"; failed → "Retrying (N/2)" or "Failed" based on total failure count against the S7 bound. Added a dedicated test: attempt 1 fails, attempt 2 succeeds → "Processing" | PASS |
| 2 (hardcoded attemptCount in Reconciled branch) | TEST | Reconciled branch now reports the real `attempts.length`; added a test with 2 prior attempts before the match | PASS |
| 3 (undocumented match-precedence) | ACCEPT (documented, not changed) | Added an explicit code comment: IC-2/G2 guarantee a `recon.match` row can only exist for a document whose latest extraction already passed validation, so a match is treated as the authoritative terminal signal — trusting that upstream guarantee, not re-deriving it from (or contradicting it against) attempt history here | N/A — no behavior change, rationale documented |
| 4 (unknown document_id) | TEST | Added an existence check — throws a clear error instead of returning a plausible-but-wrong "Processing" result; added a test | PASS |
| Untested (3+ attempts, S7-violating input) | TEST | Added a test confirming 3 failed attempt rows still resolve to "Failed — see Exceptions" (not a malformed label or crash) — the branch ordering already handled this correctly, now it's asserted, not accidental | PASS |

### Code Review
Invariant enforcement: confirmed accurate as originally stated — "None new (relies on G1/S7's underlying data)." This task is a pure reader of attempt data; it cannot violate G1 (append-only writes happen elsewhere) or S7 (attempt-count enforcement is Task 3.3's job, not yet built). Its behavior when fed an S7-violating input (3+ attempts) is now tested, per Finding disposition above, even though enforcing S7 itself remains correctly out of this task's scope.

### Scope Decisions
- Verification command satisfies EXECUTION_PLAN.md's literal path (`./scripts/test_document_status_computation.sh`) via a thin `tsx` wrapper, consistent with every other verification script this project.
- `computeDocumentStatus()` is exposed as a plain function returning `{ badge, label, attemptCount }` (not a DB view) — "a queryable field/view" per Task 2.3's own wording, interpreted as "queryable from application code," since Session 6 (the actual consumer) doesn't exist yet to dictate a concrete interface shape.

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed
[x] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[x] All FINDINGS dispositioned
[x] Pre-commit declaration recorded
[x] Code review complete (if invariant-touching)
[x] Scope decisions documented

**Status:** PASS

---

## Task 2.4 — Extract action (UI trigger + endpoint)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 2

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Click Extract on a registered document | Status transitions to "Processing", triggers extraction service | WRITTEN — 2 assertions | PASS |
| TC-2 | Uploading a document (Task 2.2) | Does not itself invoke extraction — status remains pre-Processing until Extract clicked | WRITTEN — 2 assertions | PASS |
| TC-3 | Extract button state once extraction has started | Not shown / disabled | WRITTEN — 1 assertion | PASS |
| TC-4 (G5) | Trigger Extract twice in rapid succession on same `document_id` | Exactly one extraction attempt started; second rejected | WRITTEN — 1 assertion | PASS |
| TC-5 (added) | POST extract for a non-existent `document_id` | 404 | WRITTEN — 1 assertion | PASS |
| TC-6 (added) | Real double-click on the rendered Extract button (not just two direct API calls) | Exactly one extraction started, no duplicate row/inconsistent state | WRITTEN — 2 assertions | PASS |
| TC-7 (added) | Badge display after a synthesized failed attempt | Shows Task 2.3's computed "Retrying (1/2)", not the raw internal "processing" column | WRITTEN — 1 assertion | PASS |

`ui_tests/extract-trigger.spec.ts`: 8 tests, all PASS. Full suite (28 tests): PASS, run twice for stability.

### Challenge Agent Output
Run via an independent subagent (no build-session context), evidence-only.

**Verdict:** FINDINGS — 2 items, both real defects (not just coverage gaps) — Task 2.4's own CC prompt explicitly says the displayed status should come from "Task 2.3's status computation," but the UI read the raw internal lock-state column instead.

**Findings (from the challenge):**
1. `UploadForm.tsx` displayed the raw `extracted_document.status` column (`'registered'`/`'processing'`) as the row's status text instead of calling Task 2.3's `computeDocumentStatus()` — confirmed by grep that `computeDocumentStatus` was never imported anywhere outside its own test script. Once Session 3 exists, this would have permanently shown the literal word "processing" and never "Retrying"/"Failed"/"Reconciled", regardless of actual extraction outcome.
2. The status indicator rendered with generic `badge badge-neutral` styling instead of the purpose-built `.status-badge.{state}` CSS classes already defined in `globals.css` (added ahead of this task, in the design-system-adoption commit) — those five rules were dead code.
3. (Untested Scenarios, folded into the same fix) The 404 (not-found) branch, a real UI double-click (as opposed to two direct API calls), and the Retrying/Failed/Reconciled badge states were all unexercised by any test.

**Also flagged, accepted as-is:** the G5 concurrency test proves the atomic-UPDATE guard is correct by construction, but — since `better-sqlite3` is synchronous and Node is single-threaded — it cannot demonstrate genuine multi-connection/multi-process concurrency the way the real production mechanism (Fabric row-lock, per G5's Implementation note) would face. Accepted: Fabric wiring is out of scope until Session 4; the SQL-level guard logic itself (the actual enforcement point) is what's being verified here, and it is dialect-independent.

**Finding dispositions:**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
| 1 (raw status vs. computed badge conflated) | TEST | Added `status_badge` to the `ApiDocument` wire shape (`documents.ts`) and a single shared `listDocumentsWithStatusBadge()` used by both the Upload screen's SSR initial render (`page.tsx`) and the client refresh path (`route.ts`'s `GET`) — deliberately centralized after the earlier camelCase/snake_case drift bug, so SSR and client can't diverge again. `status` (raw) still drives Extract-button visibility only; `status_badge` (Task 2.3's computation) drives the displayed text. Added TC-7: insert a synthetic failed attempt, assert the badge shows "Retrying (1/2)" | PASS |
| 2 (dead CSS, generic styling) | TEST | Row now renders `className="badge status-badge {state}"`, applying the existing per-state color rules | PASS (visual/class assertion via TC-7's badge text; class application confirmed by code) |
| 3 (untested 404 / double-click / badge states) | TEST | Added TC-5 (404), TC-6 (real double-click via the rendered button, not just API calls), TC-7 (Retrying badge, doubling as Finding 1's regression test) | PASS |

### Code Review
Required — D-I, G5.

| Invariant | Enforcement point to check | Result |
|---|---|---|
| D-I | No call site for `triggerExtraction()`/`/api/documents/[id]/extract` anywhere in `documents.ts`'s registration path — confirmed by code inspection; separately confirmed behaviorally (TC-2: upload alone leaves `status: 'registered'`) | CONFIRMED |
| G5 | Single atomic `UPDATE extracted_document SET status = 'processing' WHERE document_id = ? AND status != 'processing'`, `changes === 0` detects an already-owned document — confirmed via TC-4 (API-level race) and TC-6 (real double-click through the UI) | CONFIRMED for the SQLite/single-process case; genuine multi-connection concurrency against the real Fabric row-lock mechanism remains untested until Session 4 (documented, not silently assumed) |

### Scope Decisions
- `startExtractionPipelineStub()` in `extraction.ts` is an intentional no-op — Session 3 (not yet built) implements the real pipeline; Task 2.4's own CC prompt says to wire the trigger through to "Session 3's extraction service," which doesn't exist yet.
- The Extract button only appears on the Upload screen's document list, not on Home's "Uploaded Statements panel" (also named in Task 2.4's CC prompt) — Home only has a thin Session 1 placeholder; its real content is Task 6.1 (Session 6).
- `listDocumentsWithStatusBadge()` computes the badge per-document via `computeDocumentStatus()` (Task 2.3) inline in the list query path — O(n) status computations per page load. Acceptable at this build's scale (no pagination/volume concerns raised anywhere in the signed-off docs for the Upload screen); would need revisiting if Session 6's Home panel has different performance requirements.

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed
[x] Challenge agent run — verdict recorded (CLEAN or FINDINGS)
[x] All FINDINGS dispositioned
[x] Pre-commit declaration recorded
[x] Code review complete (if invariant-touching)
[x] Scope decisions documented

**Status:** PASS
