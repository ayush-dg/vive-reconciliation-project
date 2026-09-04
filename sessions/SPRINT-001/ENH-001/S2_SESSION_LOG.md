# SESSION_LOG.md

## Session: ENH-001 Session 2 — Multiple PDF Batch Upload
**Date started:** 2026-09-04
**Engineer:** Vaishali
**Branch:** session/s2_batch_upload
**Claude.md version:** v1.5
**Execution mode:** [ ] Autonomous (sequential, no interruption, no prediction)
                  | [x] Manual (prediction discipline, prediction before verification)
**Status:** In Progress

## Pre-Build Validation — 2026-09-04

### Schema Validation
**First run — HALT (literal), same 5 STALE-OR-INVALID IDs as Session 1** (`Claude.md`
Section 2 still labeled `IC-1`–`IC-5` at that point). Engineer directed fixing the label
now rather than waiving again, since Session 1 is fully closed out — see Claude.md v1.5
(commit `48d3dc5`, relabeled to canonical `G1`–`G5`). Schema Validation re-run after the
amendment:

**Verdict:** PASS

| Check | Status | Notes |
|---|---|---|
| Section 1: System Intent | PRESENT | |
| Section 2: Hard Invariants | PRESENT | `G1`–`G5` (relabeled from `IC-1`–`IC-5`, v1.5) |
| Section 3: Scope Boundary | PRESENT | |
| Section 4: Fixed Stack | PRESENT | |
| Section 5: Rules | PRESENT | |
| METHODOLOGY_VERSION | PRESENT | `PBVI v4.9`, matches loaded skill |
| CQ-001 complexity invariant | PRESENT | Verbatim |
| ID references resolved | ALL VALID | `G-N` is not one of the four ID patterns this check scans for (`M-NNN`/`IC-N`/`IP-NNN`/`E-NNN`) — zero flagged IDs found in Section 2 or 3 |

### Interpretation Confirmation
**Modules I will modify:** M-022 (`src/lib/extractionPipeline.ts`), M-015 (`src/lib/extraction.ts`) — Task 2.1

**Invariants I will respect:** G1–G5 (all five GLOBAL, full text in Claude.md Section 2), CQ-001. TASK-SCOPED: S7 (max 2 extraction attempts) — directly implicated, must be an explicit test case per the task's own design note, not assumed.

**Blast radius:**
  In scope: `src/lib/extractionPipeline.ts`, `src/lib/extraction.ts`, `scripts/test_extraction_crash_recovery.sh` (new)
  Out of scope: `UploadForm.tsx`/`HomeView.tsx`/`DocumentDetailView.tsx` (Session 1, done), `documents.ts` (Task 2.2's territory), `toastStore.ts`/`ToastProvider.tsx` (Task 2.4's territory), any schema/migration file (no schema change, per brief's MANDATORY constraint)
  Integration points: none new — M-022 already calls IP-001, unaffected
  Entities: none — no new columns

**Engineer response:** CONFIRMED
**Engineer notes:** N/A
**Proceed to first task:** YES

---

## Tasks

| Task Id | Task Name | Status | Commit |
|---------|-----------|--------|--------|
| 2.1     | Extraction crash-recovery fix (IC-CANDIDATE-01/R-005) | Completed | d8503ad |
| 2.2     | Sequential batch upload loop + registration-failure skip + batch cap | Completed | 63d5ecf |
| 2.3     | Per-file progress state UI | Completed | feb46eb |
| 2.4     | Running success-only toast counter | Completed | 26d4b29 |

---

## Resumed Sessions (Autonomous mode only)

N/A — Manual mode.

---

## Decision Log

| Task | Decision made | Rationale |
|------|---------------|-----------|
| Pre-Build | Fix Claude.md's `IC-N`→`G-N` label gap now (v1.5) rather than waive again | Session 1 is fully closed out; deferring further would mean carrying the same HALT into every future session indefinitely |
| 2.1 | Design gap found in the execution plan's Option B: a `skipSuccessGuard` retry with no attempt slots remaining silently no-ops instead of failing visibly. Fixed by adding `RecoveryAttemptsExhausted`, thrown instead of silently returning. | Engineer-directed after the gap was traced and presented with two options (make the no-op explicit vs. document as a known limitation) — chose to fix it, since a silent no-op that looks like success is a worse failure mode than a visible one |
| 2.1 | `needsSilverRecovery()` added to `extraction.ts` (not in the original CC prompt) | Required to make `skipSuccessGuard` reachable from a real `triggerExtraction()` call — the CC prompt specified the recovery mechanism but not how a future trigger decides to invoke it |
| 2.2 | Extracted `src/lib/batchUploadSequencing.ts` as a standalone pure function rather than writing the sequencing loop inline in `UploadForm.tsx` (as the CC prompt's literal text implies) | The "no two extractions in flight simultaneously" acceptance criterion needs to be genuinely unit-testable, matching this codebase's own convention (every other `test_*.sh` script tests `src/lib` directly, never React component internals) — the alternative was inferring timing from Playwright network waterfalls only, a weaker form of evidence |
| 2.2 | Challenge agent Finding 1/2 fix: `runBatchUploadSequenced` now treats an extraction failure the same as a registration failure (skip, continue) and an anomalous ok/no-documentId result as a no-op skip, rather than the original design's implicit assumption that extraction never throws | The function's own contract shouldn't silently depend on today's caller (`handleExtract`) happening to swallow all its own errors — defensive by construction, not by coincidence |
| 2.3 | Design Gate Finding 3's click-through gate (`batchInProgress`) implemented as a single table-wide boolean, suppressing every row's click-through (not just the current batch's own rows) while a multi-file batch is non-terminal | The actual risk (navigating away abandons the in-flight batch) exists regardless of which link the user clicks — an old, unrelated document's link is just as dangerous to click mid-batch as one of the batch's own rows |
| 2.3 | Challenge agent Finding 1/2 fix: `extractAndTrack`'s follow-up status check now has explicit failure handling (never leaves a row stuck at 'extracting') and correctly distinguishes a genuine 409-concurrent-trigger 'Processing'/'Retrying' badge from an actual terminal state | A row stuck non-terminal forever would permanently block `batchInProgress` from clearing, hiding every click-through app-wide — a worse variant of the exact Design Gate Finding 3 defect this task exists to fix |
| 2.4 | Counter tracks registration success, not extraction outcome, and only engages for `files.length > 1` | Task 2.3 already owns extraction success/failure per row; the toast literally says "uploaded"; the spec's own failure example (registration failures reduce the count) never mentions extraction. A lone file keeps its existing per-file toast — Task 2.2 already treats it as fire-and-forget, not a batch |
| 2.4 | Challenge agent Finding 1 fix: intermediate counter toasts now pass `autoDismissMs: 0` (never auto-expire mid-batch); the final count is promoted to a normal auto-dismissing toast in `handleSubmit`'s `finally` block once the batch actually settles | The default 5s auto-dismiss is shorter than a real per-file cycle (live Claude, not this suite's mock) can take — an unsuppressed running counter would flicker off mid-batch and only reappear on the next success, defeating the point of a single persistent toast. The engineer's own retroactive prediction explicitly named this exact risk and judged it irrelevant to this suite (correctly, for the mock) without registering that it still applied to production |

---

## Deviations

| Task | Deviation observed | Action taken |
|------|--------------------|--------------|
| 2.1 | `test_extraction_attempt_recording.sh` and `test_extraction_method_summary.sh` (pre-existing regression scripts, run as extra verification beyond this task's own declared command) both crashed on `UNIQUE constraint failed: extracted_vendor_registry.vendor_slug` — stale fixture rows (`summary_deterministic_vendor`, `fred_beans`) from earlier runs this session. Cleared `summary_deterministic_vendor` successfully; `fred_beans` cleanup hit a FOREIGN KEY constraint (something still references it) and was not forced. | Same pre-existing, already-documented "fixture scripts not safe to re-run against a used local DB" gap (`PROJECT_MANIFEST.md`) — not caused by this task's diff. Not chased further: `test_silver_normalization.sh` (13/13 clean) already directly re-exercises the same reordered guard logic (`hasAlreadySucceeded()`) these two scripts would also cover, giving sufficient regression confidence without forcing a risky FK-cascading delete. |
| 2.2 | The M-011 N+1 slowdown (Task 1.3/1.4's Deviations) recurred — the local test DB grew to 244 documents during this task's own repeated batch-cap/5-file/16-file test runs while authoring the new tests, and 5 different pre-existing tests in `upload.spec.ts` started failing on timeouts as a result. Reproduced the exact same signature as the earlier occurrence (slow `GET /api/documents`). | Same targeted local-sandbox reset as before (reconciliation-domain result tables only — `extracted_document` 244→0, auth and vendor-registry config preserved). Re-ran the full suite clean afterward (17/17). This is now the 2nd occurrence this sprint — see the standing Out of Scope Observation below, worth prioritizing given the recurrence rate. |
| 2.2 | Two of my own new test bugs found and fixed during authoring, not defects in the implementation: (1) the 5-file batch test checked `status_badge.label === 'Extraction success'` — wrong; Upload's raw badge shows `'Extracted'` (Home's own client-side relabeling doesn't apply here). (2) the duplicate-in-batch test used a fixed filename across repeated debugging runs, so leftover documents from earlier runs (different random content, same filename) inflated the duplicate count. | Fixed both — corrected the expected label string, and switched to a per-run-unique filename matching this file's own established convention. |
| 2.4 | **Procedural deviation, not a code defect:** implementation was built and full verification run BEFORE the engineer's Manual-mode prediction statement was obtained — the same prediction-before-verification sequencing error corrected earlier this sprint (Pre-Build entry above). Self-caught before proceeding to commit. | Disclosed to the engineer immediately, before any further action. Engineer chose to give the prediction retroactively rather than void the run — both prediction and actual result recorded side by side in `S2_VERIFICATION_RECORD.md`. No repeat expected for the remainder of this session: pause for prediction BEFORE running any verification command, every task, no exceptions. |
| 2.4 | My own test bug during authoring: the first two toast-counter tests asserted exact `textContent()` equality (e.g. `.toBe('7/10 uploaded')`), which failed — the toast `<div>` also contains its dismiss button's "×" as a sibling text node, so the real content is `'7/10 uploaded×'`. | Fixed by matching with `toMatch(/^7\/10 uploaded/)` (no end anchor) instead of exact equality — not a defect in `UploadForm.tsx`, purely a test-assertion mistake. |
| 2.4 | Both new multi-file toast tests (5-file and 10-file batches) initially failed intermittently under the file's own declared `toPass({timeout: N})` values (30_000/60_000/90_000) — traced to a pre-existing gap: no test in `upload.spec.ts` ever calls `test.setTimeout()`, so every test silently inherits Playwright's 30s default PER-TEST timeout regardless of what's declared inside an individual `toPass()` call. The pre-existing 5-file real-batch test (`toPass({timeout: 45_000})`) has the same latent exposure — it has simply been completing under 30s in practice. | Added explicit `test.setTimeout(120_000)` to both new multi-file tests so their declared inner timeouts are actually enforced. Did not touch the pre-existing test's timeout — out of scope for this task, flagged as an Out of Scope Observation below given it's a file-wide pattern. |
| 2.4 | A full-suite `upload.spec.ts` run under this project's default `fullyParallel: true` (workers unset, defaults to several) intermittently fails 1-2 PRE-EXISTING, unrelated tests (different ones each run — seen: the click-through-appears test, the extraction-genuinely-fails test) with `ECONNRESET`/stuck-navigation symptoms and matching `[WebServer] Error: aborted ECONNRESET` log lines; every failure observed reproduced cleanly when re-run in isolation (`--workers=1` or `-g`). Not caused by this task's diff (confirmed: these tests don't touch `UploadForm.tsx`'s toast logic at all). | Verified Task 2.4's own new tests pass both in isolation and inside a full-suite run every time; treated the pre-existing failures as environmental (dev-server contention under real parallel load against a single shared instance), not a regression. Logged as a new Out of Scope Observation below given the pattern recurred 3 times this session across different test pairs. |

---

## Out of Scope Observations

| Task | Observation | Nature | Recommended action |
|------|-------------|--------|--------------------|
| 2.2 | `listDocumentsWithStatusBadge()`'s N+1 query (`MODULE_CONTRACTS.md` M-011) has now degraded test reliability twice in this sprint (Session 1 Task 1.4, and again here at 244 documents) — each time from this session's own test-generated data, not production usage. The recurrence rate suggests this will keep happening for the remainder of ENH-001's build unless addressed. | FRAGILITY | BACKLOG, escalated priority — batch `computeDocumentStatus()` calls instead of N+1; a safe, repeatable test-DB reset procedure (`PROJECT_MANIFEST.md`'s existing flag) would also directly reduce how often this gets hit during active development |
| 2.4 | A duplicate-registration outcome with a legal-entity mismatch (`data.duplicate && data.legalEntityMismatch`) shows its own error toast, but `registerFile`'s shared `updateBatchRow` call on that same branch still marks the row `'done'` (identical to a genuine success) — a pre-existing quirk from Task 2.2/2.3, now made more visible by Task 2.4's persistent running counter visibly stalling short of N while every "Batch progress" row reads `'done'`. A user watching both widgets could reasonably read the counter itself as buggy. | DESIGN GAP (UX inconsistency) | BACKLOG — likely needs a distinct `BatchRowState` value (e.g. `'mismatch'` or folding it into `'failed'`) rather than silently treating it as `'done'`; a real scope decision for `batchRowState`'s design, not a one-line fix, so not folded into Task 2.4 |
| 2.4 | `upload.spec.ts` has no test ever calling `test.setTimeout()`, so every test — including the pre-existing 5-file real-batch test's declared `toPass({timeout: 45_000})` — is silently capped by Playwright's 30s default per-test timeout regardless of what's declared inside a `toPass()` call. Currently masked because real completion times have stayed comfortably under 30s in practice; a future slower environment or larger batch test would fail with a confusing "test timeout exceeded" pointing at the wrong number. | FRAGILITY (latent) | BACKLOG — audit every multi-second real-batch test in this file and add explicit `test.setTimeout()` matching (or exceeding) its own largest declared `toPass` timeout |
| 2.4 | A full default-parallel (`fullyParallel: true`) run of `upload.spec.ts` intermittently fails 1-2 pre-existing, unrelated tests with `ECONNRESET`/stuck-navigation symptoms against the single shared dev-server instance — reproduced 3 times this session (Task 2.4 verification alone), a different pair of tests each time, and every failure reproduces as a clean pass in isolation. Likely the same underlying class of issue as the N+1 DB fragility above (shared local resources under concurrent load), though not confirmed to share a root cause. | FRAGILITY | BACKLOG — consider `workers: 1` for this spec file specifically, or investigate whether the dev server / SQLite connection handling can tolerate genuine concurrent request load; until then, treat isolated (`--workers=1` or `-g`) reruns of any full-suite failure as the authoritative signal before treating it as a real regression |
| Session Integration Check | `ui_tests/loading-error-consistency.spec.ts`'s "Home, Exceptions, and Document Detail render the IDENTICAL client-side refetch error" test uses a FIXED, non-randomized upload fixture (`uploadFixture('%PDF-1.4 consistency-home')`, no per-run unique content) — root-caused via direct DB inspection: G4's own content-hash idempotency means every run resolves to the SAME document, so once that document reaches a terminal state from any past run (confirmed: extracted twice, both attempts failed, during this session's own earlier full-suite pass), every subsequent run hangs forever waiting for an "Extract" button that no longer renders for a non-`'registered'` document. Self-poisoning, and now permanently broken until that specific document is cleared or the test is fixed. **Confirmed unrelated to any of this session's 4 tasks** — the file was never touched, and the same self-poisoning bug pattern (fixed fixture content colliding with prior runs) was already fixed in 3 different places within THIS session's own new tests, but this occurrence is pre-existing, in a file outside Session 2's declared blast radius. | PRE-EXISTING BUG (test-fixture non-idempotency) | Not fixed here — out of scope for `docs/Claude.md` v1.5 Section 3's declared blast radius (`loading-error-consistency.spec.ts` is not part of ENH-001). BACKLOG — switch `uploadFixture()` to per-run-unique content, matching this file's own already-established convention elsewhere in the suite |

None otherwise noticed during Task 2.1.

---

## Claude.md Changes

| Change | Reason | New Claude.md version | Tasks re-verified |
|--------|--------|-----------------------|-------------------|
| Section 2 relabeled `IC-1`–`IC-5` → `G1`–`G5` | STALE-OR-INVALID ID finding at Pre-Build Validation, deferred from Session 1 | v1.5 (commit `48d3dc5`, on this branch) | N/A — pure relabel, no task re-verification needed (content/enforcement unchanged) |

---

## Session Completion
**Session integration check:** [x] PASSED — all 4 tasks completed, verified, challenge-agent
findings dispositioned (FIX/TEST/ACCEPT throughout, none glossed over). Session-wide regression
run: `upload.spec.ts` 26/26, `home.spec.ts`+`document-detail.spec.ts` 20/20 (all isolated —
`--workers=1`/`-g` — the authoritative signal per the Deviations entries above), full
`ui_tests/` 9-file suite otherwise clean; script-level regressions for every module touched
across 2.1/2.2/2.4 (`test_extraction_crash_recovery.sh` — 20/20 assertions before hitting the
already-documented stale-fixture FK collision from Task 2.1's own Deviations, not re-chased;
`test_batch_upload_sequencing.sh` 12/12; `test_silver_normalization.sh` 13/13;
`test:toast` 11/11; `test_bounded_retry.sh` — one known/dismissed DRIFT-001 failure, expected,
not new) all green or matching an already-known, already-dismissed state. One additional,
pre-existing, self-poisoning bug found and root-caused during this check in
`loading-error-consistency.spec.ts` (fixed non-randomized fixture content, G4 idempotency
causes it to hang on old terminal state) — confirmed unrelated to any of this session's 4
tasks (file untouched, outside declared blast radius), logged as a new Deviation, not fixed
here. Full default-parallel runs continue to show non-reproducing `ECONNRESET`/dev-server
contention on a rotating set of unrelated tests, documented, not tied to this session's diffs.
**All tasks verified:** [x] Yes — 2.1 (`d8503ad`), 2.2 (`63d5ecf`), 2.3 (`feb46eb`),
2.4 (`26d4b29`)
**Blocked tasks resolved:** [x] Yes — N/A, no BLOCKED tasks occurred
**PR raised:** [ ] Yes — PR #: [branch] → feature/pbvi_execution — not yet raised
**Status updated to:** Session integration check passed, engineer signed off — ready for PR

SIGNED OFF: Vaishali 04-09-2026

---

## Post-Sign-Off Hotfixes (Out of ENH-001 Scope)

Two small fixes made on this same branch during the engineer's manual browser QA of the
signed-off Session 2 build, discovered against real vendor PDFs and a live Azure Claude
key. Neither is part of ENH-001's task list (batch upload) or blast radius — recorded here,
lightweight-patch mode (implement + verify + commit, no Challenge Agent), same convention
as `sessions/S08_SESSION_LOG.md`/`S09_SESSION_LOG.md`'s own precedent for unscheduled fixes,
rather than silently folding them into the Session 2 task table or omitting them.

| # | Change | File(s) | Why | Verification |
|---|--------|---------|-----|---------------|
| H1 | `EXTRACTION_SYSTEM_PROMPT` now explicitly instructs Claude to exclude non-transactional summary rows ("Previous Balance", "Balance Forward", "Opening Balance", "Beginning Balance") from extracted lines | `src/lib/aiProvider.ts` | Root-caused live, against a real statement (Berlin City Auto Group / "BERLIN HEW 0726 (1) 2.pdf"): Claude included a balance-forward row (no invoice/RO number, amount -11128.26) as if it were a transaction line. That single row failed BOTH validation gates at once — structural (missing invoice_ref/ro_number) and arithmetic (the extracted-lines sum came out exactly $11,128.26 short of the statement's own total — the magnitude of that one row — because the vendor's stated total already reflects it, so counting it again double-counted it) | Typecheck clean; `EXTRACTION_SYSTEM_PROMPT`'s G3 byte-identity test (`test_prompt_injection_defense.mjs`) references the constant directly, unaffected by content changes. **Not independently confirmed against the live Claude path for Berlin specifically** — the engineer's actual retry after this fix resolved via the known-vendor DETERMINISTIC (pdfplumber) route instead of Claude (Berlin's vendor was apparently already/separately registered as a deterministic vendor), so this fix's real effect on Berlin's original failure mode remains unexercised by live data. Recorded honestly as a gap, not claimed as verified. |
| H2 | Removed the standalone "Extraction summary" per-provider panel on Document Detail; the same information (which extraction method(s) were used) is now folded directly into the existing `reconciliation-progress` sentence across all three of its states (no lines yet / not reconciled yet / complete) | `src/app/(app)/documents/[id]/DocumentDetailView.tsx`, `ui_tests/document-detail.spec.ts` | Engineer-directed: the separate panel was unwanted visual noise once the same info could live in one sentence. Found and fixed a real gap of my own construction mid-change: my first pass gated the new phrase behind `totalLines > 0`, which would have silently dropped the provider info for a genuinely FAILED extraction (zero Silver lines, but a provider WAS attempted) — exactly the case that matters most diagnostically. Fixed before commit, not after. | 4 of 10 `document-detail.spec.ts` tests rewritten to match the new consolidated text (was asserting on the removed `provider-count-*` testids); full suite 10/10 pass, `home.spec.ts` 10/10 regression pass, typecheck clean. |

**Not yet committed** — both changes and this log entry are staged for the engineer's
review before a commit.
