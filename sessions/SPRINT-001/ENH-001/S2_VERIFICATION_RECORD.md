**Session:** ENH-001 Session 2 — Multiple PDF Batch Upload
**Date:** 2026-09-04
**Engineer:** Vaishali

## Task 2.1 — Extraction crash-recovery fix (IC-CANDIDATE-01 / R-005), Silver-normalization path

### Design Gap Found and Fixed (engineer-directed, beyond the execution plan's Option B)
Traced through the literal Option B design before implementing: a `skipSuccessGuard`
retry bypasses `hasAlreadySucceeded()`, but does not create a new attempt slot. If the
attempt that failed Silver normalization was already S7's last allowed attempt (attempt
2 of 2), the recovery retry's own `while (attemptNo < MAX_ATTEMPTS)` loop guard never
executes — the function silently returns having done nothing, indistinguishable from a
successful retry to the caller. Fixed by adding `RecoveryAttemptsExhausted`, thrown
instead of silently returning when no attempt slots remain. `extraction.ts`'s new
`needsSilverRecovery()` helper decides whether to pass `skipSuccessGuard` on each
trigger, and its catch block returns a distinct `recovery_exhausted` reason so the API
route (also touched, `route.ts`) can surface an honest 422 instead of a misleading
"already in progress" 409.

### Test Cases Applied
Source: ENH-001_EXECUTION_PLAN.md Session 2 (as amended at Phase 4 Design Gate) + the
engineer-directed gap fix above

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| TC-1 | Extraction succeeds, Silver normalization throws | `SilverNormalizationFailure` specifically thrown; attempt row still correctly written pass=1/1; zero Silver rows | PASS |
| TC-2 | `skipSuccessGuard` retry, 1 attempt slot remaining | Succeeds; 2 total attempts; Silver rows now exist; `Extracted` badge | PASS |
| TC-3 | `skipSuccessGuard` retry, 0 attempt slots remaining | `RecoveryAttemptsExhausted` thrown, not a silent no-op; no 3rd attempt row | PASS |
| TC-4 | `triggerExtraction()` end-to-end recovery | Status resets to `'registered'` after Silver failure; next trigger auto-detects via `needsSilverRecovery()` and recovers | PASS |
| TC-5 | G5 regression — concurrent trigger while genuinely processing | Rejected (`already_processing`), no attempt made | PASS |
| TC-6 (added post-challenge, Finding 1) | `triggerExtraction()` (not raw pipeline) hits exhausted recovery | `{ok:false, reason:'recovery_exhausted'}`; status reset to `'registered'` | PASS |
| TC-7 (added post-challenge, Finding 2) | Generic, uncategorized error (neither special-cased type) | Rethrown to caller, not swallowed; status still reset to `'registered'`; attempt row still written (S10 unaffected) | PASS |

Regression: `scripts/test_bounded_retry.sh` (S7) and `scripts/test_silver_normalization.sh`
(Task 3.6, directly re-exercises the reordered `hasAlreadySucceeded()` guard via its own
TC-6) both re-run clean. `npm run typecheck` clean.

### Prediction Statement
**Engineer's prediction (2026-09-04), before running `test_extraction_crash_recovery.sh`:**
TC-1/TC-3/TC-4/TC-5 predicted PASS (code paths walked and confirmed by hand). TC-2
predicted to FAIL on its last assertion — badge check expected `'Extracted'`, test as
written checked `'Processing'` (a copy-paste slip, not a defect in the fix) — with the
correct root cause named exactly (`documentStatus.ts`'s badge logic returns `'Extracted'`
once the latest attempt has passed; `'Processing'` only applies when there is no attempt
yet at all).

**Actual result:** Matched exactly on which assertion would fail and why. Discrepancy
only in the reported failure *count* — predicted "4 test case(s) FAILED" (assuming
one count per TC-block), actual was "1 test case(s) FAILED" (the counter increments per
individual assertion, and only the one wrong literal failed — the rest of TC-2 and all
of TC-1/3/4/5 passed as predicted). Fixed the one-line test assertion
(`'Processing'` → `'Extracted'`); re-run confirmed all pass.

### Challenge Agent Output
Same mechanism note as Session 1 (fresh context-free subagent substituting for
`./tools/challenge.sh`'s `claude --print` call, not available as a nested CLI invocation
in this environment).

**Verdict:** FINDINGS (2 items) — both dispositioned TEST, both now passing.

**Untested scenarios (from challenge agent, informational — 3 of 5 not promoted to
Verdict Findings requiring disposition):**
1. **[Promoted to Finding 1]** `recovery_exhausted` path had zero coverage anywhere —
   `grep -rn "recovery_exhausted"` across the repo returned only the 3 production-code
   lines defining/throwing/checking it.
2. **[Promoted to Finding 2]** The generic-error fallthrough (neither special-cased
   type) — status reset + rethrow — untested at every level.
3. Repeated `triggerExtraction()` calls after `recovery_exhausted` — does it
   deterministically keep returning `recovery_exhausted` rather than misbehaving on a
   second call? Not separately tested; TC-6's assertions on status after the exhausted
   result give reasonable confidence (state is unchanged, so `needsSilverRecovery()`
   and the exhaustion check would both re-evaluate identically) — not formally proven
   with a second consecutive call.
4. Concurrent `triggerExtraction()` calls specifically on a document where
   `needsSilverRecovery()` evaluates true (vs. TC-5's coverage of concurrency only on an
   already-`'processing'` document). Not actioned — the `needsSilverRecovery()` read
   happens before the same unchanged G5 atomic guard; a genuine race here would need
   multi-process infrastructure this repo's test style doesn't have (see Known Untested
   Scenarios below).
5. True multi-process/OS-level concurrency and the real Next.js HTTP response shape for
   an unhandled exception escaping the route handler — both out of scope, see below.

**Unverified assumptions (from challenge agent):**
1. `needsSilverRecovery()`'s `silverCount === 0` check assumes `normalizeToSilver()` is
   all-or-nothing (no partial writes on failure) — independently confirmed by
   `test_silver_normalization.sh`'s own TC-7 ("the aborted transaction leaves zero
   partial silver rows"), re-run clean as part of this task's regression pass (see Code
   Review below), rather than re-proven redundantly in this task's own harness.
2. `getExistingAttemptCount()` computed earlier than before, assumed behavior-neutral
   for ordinary callers — `test_silver_normalization.sh` (TC-6, re-invocation idempotency)
   and `test_bounded_retry.sh` both directly re-exercise this exact reordered logic and
   pass clean; `test_extraction_attempt_recording.sh`/`test_extraction_method_summary.sh`
   also re-run, but both hit the pre-existing, already-documented "fixture scripts not
   safe to re-run against a used local DB" gap (stale vendor-slug rows from earlier runs
   this session, unrelated to this diff) — not chased further given the two suites that
   did run clean already exercise the same reordered statements.

**Invariant coverage gaps:** NONE remaining after TC-6/TC-7 — G5's ownership-release
behavior is now tested at both the raw-exception level (TC-3) and the `triggerExtraction()`
level (TC-6, TC-7).

**Scope boundary observations:** None — diff confined to declared files
(`extractionPipeline.ts`, `extraction.ts`, `route.ts`, the new test script).

**Finding dispositions:**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
| 1 (`recovery_exhausted` untested end-to-end) | TEST | Added TC-6: drives the exhausted-recovery scenario through `triggerExtraction()` itself (not the raw pipeline), confirming the distinct failure reason and status reset | PASS |
| 2 (generic-error fallthrough untested) | TEST | Added TC-7: forces a genuine, uncategorized error by reproducing the exact historical bug `vendorIdentification.ts`'s own doc comment describes (a vendor registry row naming a table that was never created) via the test-fixture deterministic-route path, which has no `ensureVendorStmtTable()` safety net | PASS |

### Code Review
**G5 (required — this task extends G5's enforcement):** Confirmed `extraction.ts`'s
atomic guard —
`` UPDATE extracted_document SET status = 'processing' WHERE document_id = ? AND status != 'processing' ``
— is byte-for-byte unchanged from before this task. The only change is what happens
*after* this UPDATE succeeds (the new try/catch and its three-way error handling).

### Scope Decisions
Two scope extensions beyond the execution plan's literal text, both engineer-directed
after being surfaced during the build: the `RecoveryAttemptsExhausted` gap (see Design
Gap section above), and `needsSilverRecovery()`'s decision logic in `extraction.ts` (not
named in the original CC prompt, but required to make `skipSuccessGuard` actually
reachable from a real trigger call rather than only from a direct, internal
`runExtractionPipeline()` call).

### BCE Impact
M-022 (`extractionPipeline.ts`) — new exported error classes, new optional parameter, no
change to existing call signature compatibility. M-015 (`extraction.ts`) — new
`needsSilverRecovery()` helper, new `TriggerExtractionResult` variant, new try/catch
around the pipeline call. `route.ts` (M-044's sibling extract route, not separately
M-numbered in the touch points table) — new 422 response branch.

| Artifact | Field | Change |
|---|---|---|
| MODULE_CONTRACTS.md | M-022 "No rollback of the 'processing' status column if the pipeline throws" (M-015's known-fragility note) | This fragility is now fixed — note is stale as of this task, to be corrected in `ENH-001_BCE_IMPACT.md` at Phase 8 close-out, not edited in `discovery/` mid-sprint per Rule 3/sprint doctrine |

### Verification Verdict
[x] All planned cases passed (27/27 assertions, `test_extraction_crash_recovery.sh`)
[x] Challenge agent run — verdict recorded — FINDINGS (2), both TEST-dispositioned
[x] All FINDINGS dispositioned — ACCEPT with rationale or TEST with result
[x] Pre-commit declaration recorded — see below
[x] Code review complete (G5 — confirmed unchanged)
[x] Scope decisions documented

**Status:** COMPLETE. Prediction statement compared to actual result (see above). Awaiting
engineer commit confirmation per Manual mode.

### Pre-Commit Declaration
**Functions touched:** `runExtractionPipeline()` (new optional param, restructured guard
ordering) and `normalizeToSilver()`'s catch site (error type only) in
`extractionPipeline.ts`; `triggerExtraction()` (new try/catch, new helper
`needsSilverRecovery()`) in `extraction.ts`; the `POST` handler in
`src/app/api/documents/[id]/extract/route.ts` (new response branch).
**New exports:** `SilverNormalizationFailure`, `RecoveryAttemptsExhausted` (both from
`extractionPipeline.ts`).
**Schemas touched:** None — no migration, no new column, per the brief's MANDATORY
constraint.
**Config touched:** None.
**Files touched:** `src/lib/extractionPipeline.ts`, `src/lib/extraction.ts`,
`src/app/api/documents/[id]/extract/route.ts`, `scripts/test_extraction_crash_recovery.mjs`
(new), `scripts/test_extraction_crash_recovery.sh` (new) — all within declared blast
radius (Interpretation Confirmation, Session Log).
**Scope confirmed:** YES — within `docs/Claude.md` v1.5 Section 3 (`/src/**`, `/scripts/**`).
**Invariants touched:** G5 (enforcement extended, guard itself unchanged — confirmed by
code review above). No new invariant.

---

## Task 2.2 — Sequential batch upload loop + registration-failure skip + batch cap

### Design Note
The CC prompt's literal design (register file N, await its extraction, then register
file N+1 — for every batch, including size 1) conflicts with a pre-existing regression
requirement: single-file uploads are relied on elsewhere (a pre-existing test,
"a second PDF can be uploaded while the first one is still extracting") to be
fire-and-forget on extraction. Resolved by making the sequencing policy explicitly
size-dependent: a 1-file batch preserves the exact old behavior; a 2+-file batch awaits
each file's full register+extract cycle before the next file's registration (new,
tested). Extracted into `src/lib/batchUploadSequencing.ts`'s `runBatchUploadSequenced` —
a pure, framework-agnostic function — specifically so this policy is directly
unit-testable without a browser, matching this codebase's established convention (all
other `test_*.sh`/`.mjs` scripts test `src/lib` modules directly, never React/Playwright
internals).

### Test Cases Applied
Source: ENH-001_EXECUTION_PLAN.md Session 2

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| TC-1 | 3-file batch, instrumented delays | Never more than 1 extraction in flight; each fully completes before the next starts | PASS |
| TC-2 | Single-file batch | Function returns without awaiting the file's extraction (byte-for-byte regression) | PASS |
| TC-3 | Registration failure mid-batch (3 files, middle fails) | Batch does not abort; extraction never called for the failed file; both others still process | PASS |
| TC-4 | Same file registered twice (fakes) | Extraction only triggered once, not for the duplicate | PASS |
| Playwright: 15-file cap | Exactly 15 files selected | Accepted, no validation error | PASS |
| Playwright: 16-file cap | 16 files selected | Rejected outright with a clear message — no partial 15-of-16 kept | PASS |
| Playwright: 5-file batch | 5 real extractable PDFs | All 5 reach `'Extracted'` badge state | PASS |
| Playwright: mid-batch registration failure | 3 files, middle one genuinely invalid (no MIME, non-.pdf) | Files 1 and 3 both still registered; bad file never registered | PASS |
| Playwright: same file twice (real API, Design Gate Finding 2) | Real duplicate bytes selected twice in one 3-file batch | Registers exactly once (G4); batch continues to the 3rd file | PASS |

### Prediction Statement
N/A — per the engineer's direction, the prediction-then-verify exercise was skipped for
this task since verification had already been run and stabilized while authoring the new
test infrastructure itself (see chat record); asking for a prediction against an already-
known-passing state would have been a formality, not a genuine cognitive check.

### Challenge Agent Output
Same mechanism note as Task 2.1 (fresh context-free subagent).

**Verdict:** FINDINGS (4 items) — all four dispositioned FIX/TEST, all now passing.

**Invariant coverage gaps (from challenge agent):** G4 (sequential-duplicate-in-batch)
was only verified against instrumented fakes, never the real `registerDocument()` via a
real Playwright test — closed by the new "same file twice (real API)" test above.
CQ-001 nesting-depth compliance for `runBatchUploadSequenced` was asserted but never
checked — reviewed by hand as part of the Finding 1/2 fix (see Code Review below); the
fix's early-continue restructuring is flatter than the original, max 1 level of
conditional nesting inside the `for` loop, well within the 2-level cap.

**Finding dispositions:**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
| 1 (unguarded extraction failure could abort remaining batch) | FIX | `handleExtract` (the real implementation) never actually rejects today, confirmed by code review — but `runBatchUploadSequenced`'s own contract shouldn't silently depend on that. Added an internal try/catch around the extraction call, symmetric to registration-failure handling. Added TC-5. | PASS |
| 2 (anomalous ok:true/duplicate:false/documentId:null silently mishandled) | FIX | Added an explicit `continue` for this case — the real API never produces it, but the type allows it, and silently falling through was worse than an explicit no-op skip. Added TC-6. | PASS |
| 3 (G4 sequential-duplicate only tested against fakes) | TEST | Added a real Playwright test uploading identical bytes twice within one 3-file batch through the actual API, confirming exactly 1 registration and that the batch continues to the 3rd file | PASS |
| 4 (CQ-001 nesting compliance unstated) | ACCEPT (now improved) | Reviewed by hand: the Finding 1/2 fix's early-continue restructuring reduced nesting further (max 1 level inside the loop) — compliant, and now more clearly so than before. No test needed; this is a static structural property. | N/A (code review) |

### Code Review
**G4 (required — task's own note: "touched implicitly"):** Confirmed
`registerDocument()` itself is untouched by this task — the new sequencing loop calls
the same existing registration endpoint per file, in order, with no batching or
short-circuiting of its own duplicate-detection logic. The real-API duplicate test
(Finding 3's fix) confirms this holds end-to-end, not just by inspection.
**CQ-001:** See Finding 4 disposition above.

### Scope Decisions
Extracted `src/lib/batchUploadSequencing.ts` as a new, small module beyond the CC
prompt's literal text (which described the policy inline in `UploadForm.tsx`) —
engineer-directed choice to make the "no two extractions in flight" acceptance criterion
genuinely unit-testable per this codebase's established test conventions, rather than
only inferrable from Playwright network timing.

### BCE Impact
M-070 (`UploadForm.tsx`) — multi-file selection, new sequencing logic, batch cap. New
module `src/lib/batchUploadSequencing.ts` — not yet M-numbered (post-Phase-8 addition,
to be recorded in `ENH-001_BCE_IMPACT.md` at Phase 8 close-out, not `discovery/`
mid-sprint). M-011 (`documents.ts`) — not modified, confirmed by code review (G4 above).

| Artifact | Field | Change |
|---|---|---|
| MODULE_CONTRACTS.md | New module, no M-NNN ID yet | `src/lib/batchUploadSequencing.ts` will need an ID assignment at Phase 8 close-out (`ENH-001_BCE_IMPACT.md`), not `discovery/` mid-sprint |

### Verification Verdict
[x] All planned cases passed (12/12 pure-function assertions; 17/17 Playwright tests in
    `upload.spec.ts`; 20/20 in `home.spec.ts`+`document-detail.spec.ts` regression)
[x] Challenge agent run — verdict recorded — FINDINGS (4), all dispositioned
[x] All FINDINGS dispositioned — FIX (2), TEST (1), ACCEPT-with-improvement (1)
[x] Pre-commit declaration recorded — see below
[x] Code review complete (G4, CQ-001 — both confirmed above)
[x] Scope decisions documented

**Status:** COMPLETE. Awaiting engineer commit confirmation per Manual mode.

### Pre-Commit Declaration
**Functions touched:** `UploadForm.tsx` — `pickFile`→`pickFiles`, `handleSubmit`
restructured, new `registerFile` helper (formerly inline in `handleSubmit`). New file
`src/lib/batchUploadSequencing.ts` — `runBatchUploadSequenced`.
**Schemas touched:** None.
**Config touched:** None.
**Files touched:** `src/app/(app)/upload/UploadForm.tsx`, `src/lib/batchUploadSequencing.ts`
(new), `scripts/test_batch_upload_sequencing.mjs` (new), `scripts/test_batch_upload_sequencing.sh`
(new), `ui_tests/upload.spec.ts` — all within declared blast radius.
**Scope confirmed:** YES — within `docs/Claude.md` v1.5 Section 3 (`/src/**`, `/scripts/**`, `/ui_tests/**`).
**Invariants touched:** G4 (touched implicitly, confirmed unbypassed by code review + a
real end-to-end test). No new invariant.

---

## Task 2.3 — Per-file progress state UI

### Design Note
A new state array (`batchRows: BatchRow[]`) tracks each file's progress
(`queued`/`registering`/`extracting`/`done`/`failed`) keyed by a fresh id assigned at
selection time — a queued/registering file has no `document_id` yet, so it can't be
represented in the historical "Uploaded statements" table at all. `registerFile` and
a new `extractAndTrack` wrapper (around `handleExtract`) drive the row's state as the
sequential loop progresses. Design Gate Finding 3's click-through gate
(`batchInProgress`) is a single table-wide derived boolean — applied to every row in
the historical table, not scoped to the current batch's own rows — since the actual
risk (navigating away abandons the batch) exists regardless of which link is clicked.

### Test Cases Applied
Source: ENH-001_EXECUTION_PLAN.md Session 2

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| TC-1 | Mid-3-file-batch snapshot | Not all rows terminal yet; at least one still queued/registering/extracting | PASS |
| TC-2 | Registration failure mid-batch | Failed row distinct from done rows (`['done','failed']`) | PASS |
| TC-3 | Single-file batch | Full progression reaches `'done'` (fire-and-forget extraction still tracked) | PASS |
| TC-4 (Finding 3) | Click-through during active batch | Absent on a done row while any sibling row is non-terminal | PASS |
| TC-5 (Finding 3) | Click-through once batch fully terminal | Visible on all done rows, checked on the live page (not after reload) | PASS |
| TC-6 (added post-challenge, Finding 3) | Old, unrelated already-completed document during a new batch | Its click-through is ALSO suppressed (table-wide, not per-row) and reappears once the new batch finishes | PASS |

### Prediction Statement
N/A — same rationale as Task 2.2 (implementation and its own new test suite were
authored and stabilized together; a retroactive prediction on an already-verified state
would be a formality, not a genuine cognitive check).

### Challenge Agent Output
Same mechanism note as prior tasks (fresh context-free subagent).

**Verdict:** FINDINGS (4 items) — 2 FIX, 1 TEST, 1 ACCEPT (documented, not fixed).

**Unverified assumptions / untested scenarios not promoted to findings:**
Task 2.1's actual server-restart crash-recovery path and CI timing sensitivity of the
5-second mid-batch polling window were both noted as genuinely out of scope (requires
process restart / infra timing, not exercisable through this task's modified files).

**Finding dispositions:**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
| 1 (`extractAndTrack`'s follow-up GET has no failure handling — permanently stuck 'extracting', blocking `batchInProgress` app-wide) | FIX | Added a `try/catch` and an explicit non-ok check — both now resolve the row to `'failed'` rather than leaving it stuck. Also handles the document-not-found-in-response case the same way (Finding 1's own principle: always resolve to *some* terminal state, never leave it stuck). | Covered by existing TCs continuing to pass; no dedicated failure-injection test added (would require intercepting the specific follow-up GET mid-batch — noted as a residual, low-priority gap, not chased further given the fix itself is simple and directly addresses the described mechanism) |
| 2 (409-concurrent-trigger badge could be `Processing`/`Retrying`, ternary treated it as `'done'`) | FIX | Replaced the two-outcome ternary with an explicit check: `'Failed'` → `'failed'`; `'Processing'`/`'Retrying'` → left non-terminal (no premature update); anything else → `'done'` | Existing TCs unaffected (none currently exercise the 409 sub-case — same residual gap as Finding 1, narrow and requires an external concurrent trigger) |
| 3 (cross-batch suppression — old/unrelated document — untested) | TEST | Added a test: fully extract a document first, start an unrelated new batch, confirm the old document's click-through is ALSO hidden while the new batch is non-terminal, and reappears once it finishes | PASS |
| 4 (starting a new batch drops a still-pending single-file batch's progress row) | ACCEPT | Documented in code: `batchRows` is an ephemeral, live display only — the "Uploaded statements" table remains the source of truth for the file's actual final state regardless. Fixing this would mean either confusing cross-batch row merging or blocking new uploads while any extraction is pending (defeats fire-and-forget for single files) | N/A — accepted, not fixed |

### Code Review
No invariant enforcement point touched — confirmed by the challenge agent against
G1-G5; this task is presentation/state-derivation only, layered on unchanged
`handleExtract`/registration/extraction endpoints.

### Scope Decisions
Findings 1/2's fix touches `extractAndTrack` (already declared in scope from this
task's own new-function addition) — no scope expansion. Finding 3's test is within the
same file already in scope. Finding 4 is a documented, accepted limitation, not a code
change.

### BCE Impact
M-070 (`UploadForm.tsx`) — new client-side progress-tracking state and rendering, no
interface/contract change to any backend module. No new touch point.

| Artifact | Field | Change |
|---|---|---|
| MODULE_CONTRACTS.md | M-070 description | No change — per-file progress UI is presentation-layer only |

### Verification Verdict
[x] All planned cases passed (23/23 in `upload.spec.ts`, 20/20 regression)
[x] Challenge agent run — verdict recorded — FINDINGS (4): 2 FIX, 1 TEST, 1 ACCEPT
[x] All FINDINGS dispositioned
[x] Pre-commit declaration recorded — see below
[x] Code review complete (no invariant touched, confirmed)
[x] Scope decisions documented

**Status:** COMPLETE. Awaiting engineer commit confirmation per Manual mode.

### Pre-Commit Declaration
**Functions touched:** `UploadForm.tsx` — `pickFiles` (now assigns per-file ids),
`registerFile` (now drives row state), new `updateBatchRow`/`updateBatchRowByDocumentId`
helpers, new `extractAndTrack`, `handleSubmit` (seeds `batchRows`), new `batchInProgress`
derived value, click-through condition gated by it.
**New types:** `BatchFile`, `BatchRowState`, `BatchRow` (all local to `UploadForm.tsx`).
**Schemas touched:** None.
**Config touched:** None.
**Files touched:** `src/app/(app)/upload/UploadForm.tsx`, `ui_tests/upload.spec.ts` —
both within declared blast radius.
**Scope confirmed:** YES — within `docs/Claude.md` v1.5 Section 3 (`/src/**`, `/ui_tests/**`).
**Invariants touched:** None — confirmed by challenge agent and code review.
