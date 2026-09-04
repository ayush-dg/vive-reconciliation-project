# ENH-001_EXECUTION_PLAN.md — UI clarity fixes + multiple PDF upload

**Enhancement:** ENH-001
**Sprint:** SPRINT-001
**Type:** A · **Sign-Off Tier:** 2 (reconfirm per SCOPE.md Section 7 once session count below is locked)
**Sessions:** 2

Session 1 is the low-risk, fully-evidenced UI clarity half. Session 2 is the batch-upload
half, which carries all the real design decisions from Phase 1 (crash recovery, sequencing,
skip-on-failure, toast counter). Splitting them this way means Session 1 can complete and
be verified independently of Session 2's larger surface — if Session 2 loops, Session 1's
work is already banked.

---

# Session 1 — UI Clarity Fixes (Home / Upload / Document Detail)

**Session goal:** Home, Upload, and Document Detail read clearly at a glance — combined
summary, fewer noise columns, a working click-through, IST timestamps, and unambiguous
stage labels. No batch upload work in this session.

## Task 1.1 — Status label renames

**Description:** Rename the two ambiguous labels in `HomeView.tsx`'s existing badge-label
mapping function — 'Success' → 'Extraction success', 'Done' → 'Recon done' — so it's clear
which stage (extraction vs. reconciliation) actually completed. Same function that already
carries the 2026-08-31 exception-softening logic; no new touch point.

**CC prompt:**
```
In src/app/(app)/home/HomeView.tsx, locate the badge-label mapping function (the one
returning { label, showExceptionsLink, badgeClass } — same function with the 2026-08-31
'Failed' + open_exception_count softening logic already in it). Change the two label
string literals only:
  'Success' -> 'Extraction success'
  'Done' -> 'Recon done'
Do not change badgeClass, showExceptionsLink, or any branching logic. This is a 2-line
string edit, nothing else in this function changes.
```

**Test cases:**
- Happy path: a document with `status_badge = 'Extracted'` renders the label "Extraction
  success".
- Happy path: a document with `status_badge = 'Reconciled'` (no open exceptions) renders
  "Recon done".
- Regression: a document with `status_badge = 'Reconciled'` and open exceptions still
  renders "Recon done" with the exceptions link — unaffected by the rename.

**Verification command:**
```bash
npx playwright test ui_tests/home.spec.ts
```

**Invariant enforcement:** None — display-string change only.

**Regression classification:** REGRESSION-RELEVANT — extends existing `home.spec.ts`.

**UI test spec:**
```
Screen: Home
Test strategy: Seeded — tests run against seed state
Assertions to implement:
- Extracted-status document shows "Extraction success" label
- Reconciled-status document (no exceptions) shows "Recon done" label
- Reconciled-status document (with exceptions) still shows "Recon done" + exceptions link
Test file path: ui_tests/home.spec.ts (extend existing)
```

---

## Task 1.2 — Document Detail: combined summary + drop two columns

**Description:** Combine the extraction and reconciliation summary into one display block
on Document Detail, and remove the **Confidence** and **Provider** columns from the
extracted-lines table — both are per-attempt values duplicated identically across every
line of a document, not per-line data, and both remain visible elsewhere on the page via
the existing extraction-method summary block (Task 3.5's `providerEntries`).

**CC prompt:**
```
In the Document Detail screen (DocumentDetailView.tsx, backed by documentDetail.ts's data
assembly), combine the currently-separate extraction summary and reconciliation summary
into a single display section — same data already assembled by documentDetail.ts, this is
a presentation-layer change only, not a data-assembly change. Remove the Confidence and
Provider columns from the extracted-lines table UI only — do NOT remove the `confidence`
or `providerUsed` fields from documentDetail.ts's StatementLine type or its query; they
stay computed and returned, just not rendered as table columns. The existing extraction-
method summary block (providerEntries, Task 3.5) is unaffected and continues to show
provider breakdown at the document level.
```

**Test cases:**
- Happy path: Document Detail renders one combined summary block, not two separate ones.
- Happy path: the extracted-lines table renders without Confidence and Provider columns.
- Regression: `documentDetail.ts`'s `confidence`/`providerUsed` fields are still returned
  by the data layer (removal is UI-only) — verifiable at the data-assembly level, not just
  the rendered table.
- Regression: the extraction-method summary block (provider breakdown) still renders
  correctly, unaffected by the per-line column removal.
- Regression: all other table columns and the summary's underlying values (extraction
  status, reconciliation status, exception count) still display correctly.

**Verification command:**
```bash
npx playwright test ui_tests/document-detail.spec.ts
```

**Invariant enforcement:** None — presentation-layer only, no change to `documentDetail.ts`'s
data assembly (M-013).

**Regression classification:** REGRESSION-RELEVANT — extends existing `document-detail.spec.ts`.

**UI test spec:**
```
Screen: Document Detail
Test strategy: Seeded — tests run against seed state
Assertions to implement:
- Combined summary block present; separate extraction/reconciliation blocks absent
- Extracted-lines table does not render Confidence or Provider columns
- Extraction-method summary block (provider breakdown) still renders correctly
- Remaining columns and summary values unchanged from pre-task state
Test file path: ui_tests/document-detail.spec.ts (extend existing)
```

---

## Task 1.3 — Click-through from Upload to a document's extracted lines

**Description:** Add a link/action on the Upload screen that navigates to a document's
extracted lines once extraction completes, so the user doesn't have to separately navigate
via Home. **Note (added at Design Gate):** in Session 2's batch context, this task's
click-through visibility is further constrained by Task 2.3's Finding-3 fix — suppressed
until the whole batch is terminal, not just the individual row. This task builds the
click-through itself; Task 2.3 gates it once batch upload exists.

**CC prompt:**
```
In UploadForm.tsx, once a file's extraction completes successfully (existing per-file
status tracking), render a click-through link/action to that document's Document Detail
extracted-lines view (reuse the existing route Document Detail already uses — no new route).
Only shown once extraction has actually completed for that row, not during Processing/
Extracting states.
```

**Test cases:**
- Happy path: after a single-file upload completes extraction, a click-through link
  appears and navigates to that document's extracted lines.
- Failure case: while extraction is still in progress for a file, no click-through is shown.
- Failure case: if extraction fails for a file, no click-through to (nonexistent) extracted
  lines is shown.

**Verification command:**
```bash
npx playwright test ui_tests/upload.spec.ts
```

**Invariant enforcement:** None.

**Regression classification:** REGRESSION-RELEVANT — extends existing `upload.spec.ts`.

**UI test spec:**
```
Screen: Upload
Test strategy: Seeded — tests run against seed state
Assertions to implement:
- Click-through link appears only after extraction completes for a row
- Link navigates to the correct document's Document Detail extracted-lines view
- No link shown while Processing or on extraction failure
Test file path: ui_tests/upload.spec.ts (extend existing)
```

---

## Task 1.4 — Upload time display in IST

**Description:** Display upload timestamps in IST across Home and Document Detail, fixed
(not user/locale-configurable), per the brief's OPTIONAL constraint.

**CC prompt:**
```
Format all displayed upload_timestamp values (Home list, Document Detail) in IST
(Asia/Kolkata), fixed — no locale/timezone selector. Underlying stored timestamp
(A01/E-001's upload_timestamp field) is unchanged; this is a display-formatting change only.
```

**Test cases:**
- Happy path: a document's upload timestamp displays correctly converted to IST on Home.
- Happy path: same on Document Detail.
- Regression: the underlying stored UTC (or as-stored) value is unaffected — only display
  formatting changes.

**Verification command:**
```bash
npx playwright test ui_tests/home.spec.ts ui_tests/document-detail.spec.ts
```

**Invariant enforcement:** None — display formatting only, no change to A01/E-001's
stored field.

**Regression classification:** REGRESSION-RELEVANT — extends existing specs.

**UI test spec:**
```
Screen: Home, Document Detail
Test strategy: Seeded — tests run against seed state with a known upload_timestamp
Assertions to implement:
- Known UTC timestamp displays as the correct IST-converted value on both screens
Test file path: ui_tests/home.spec.ts, ui_tests/document-detail.spec.ts (extend existing)
```

---

# Session 2 — Multiple PDF Batch Upload

**Session goal:** A user can select and upload multiple PDFs in one action. Files process
sequentially with visible per-file progress, a running success-only toast counter, a
15-file cap, registration failures are skipped not fatal, and the extraction lock's
crash-recovery gap (IC-CANDIDATE-01) is fixed as part of enabling this safely.

## Task 2.1 — Extraction crash-recovery fix (IC-CANDIDATE-01 / R-005), Silver-normalization path

**Description:** `runExtractionPipeline`'s per-attempt failures (validation gate misses)
are already self-healing — caught internally, attempt row written (S10), loop retries or
returns normally within S7's 2-attempt cap. The real gap is narrower and different in
kind: when extraction *succeeds and validates* but the subsequent `normalizeToSilver()`
call throws, the attempt row is already written showing a pass (`arithmetic_pass=1,
structural_pass=1`), and `hasAlreadySucceeded()` — checking only those flags, not whether
Silver rows actually exist — would make any naive retry silently no-op forever. The
document ends up permanently displaying "Extraction success" with zero usable line data
and no path to fix it.

**Design (Option B — narrow, doesn't alter `hasAlreadySucceeded`'s existing contract for
any other caller):**
1. In `extractionPipeline.ts` (M-022), replace the generic re-thrown `Error` around the
   `normalizeToSilver` call with a distinguishable error type (e.g. a
   `SilverNormalizationFailure` class extending `Error`), exported from the module.
2. Add an optional parameter to `runExtractionPipeline` — e.g.
   `runExtractionPipeline(documentId, { skipSuccessGuard?: boolean })`, default `false` —
   that bypasses the `hasAlreadySucceeded()` early-return only when explicitly set. No
   change to the function's behavior for any existing caller (they don't pass this option).
3. In `extraction.ts` (M-015), the crash-recovery `catch` block specifically checks
   `instanceof SilverNormalizationFailure`. On that specific error: reset status to
   re-triggerable, and the next trigger calls `runExtractionPipeline(documentId, {
   skipSuccessGuard: true })`. Any other thrown error (the `if (!document) throw`
   not-found case) gets a plain status reset with no special retry path — that's a
   data-integrity condition, not something retrying fixes.

**S7 interaction — no special-casing needed, verify by construction:** `getExistingAttemptCount`
already counts the "passed but unsaved" attempt row. If that was attempt 2 (the final
allowed attempt), `skipSuccessGuard: true` bypasses `hasAlreadySucceeded` but the loop's
own `while (attemptNo < MAX_ATTEMPTS)` guard — using the same count — still prevents a
3rd attempt. The cap holds automatically; this must be a test case, not assumed.

**CC prompt:**
```
In src/lib/extractionPipeline.ts:
1. Define and export a SilverNormalizationFailure error class (extends Error).
2. In the block that calls normalizeToSilver(documentId, vendor.vendorId, extracted),
   throw SilverNormalizationFailure (with the same contextual message currently used)
   instead of a plain Error.
3. Add an options parameter to runExtractionPipeline: (documentId: string, options?:
   { skipSuccessGuard?: boolean }). Default skipSuccessGuard to false. When true, skip
   the `if (hasAlreadySucceeded(documentId)) return;` early check — do not change any
   other behavior, including the while-loop's own MAX_ATTEMPTS bound.

In src/lib/extraction.ts, wrap the existing call site
(await runExtractionPipeline(documentId);) in try/catch. On a caught
SilverNormalizationFailure: reset extracted_document.status to a re-triggerable state (not
'processing'). On any other caught error (e.g. document-not-found): reset status the same
way, but do not imply retry will help — this is a plain status unstick, not a recovery
path with a defined next step. Do NOT touch the G5 atomic guard
(`UPDATE ... WHERE status != 'processing'`) above this call site — this task only adds
recovery after the guard has already succeeded and ownership acquired. No schema change.

A subsequent manual re-trigger of a SilverNormalizationFailure-reset document must call
runExtractionPipeline(documentId, { skipSuccessGuard: true }) — wire this through
extraction.ts's normal trigger path, distinguishing a fresh document (skipSuccessGuard:
false, default) from a post-Silver-failure retry.
```

**Test cases:**
- Happy path: `runExtractionPipeline` succeeds — status transitions normally, unchanged
  behavior, `skipSuccessGuard` never relevant.
- Failure case (validation-gate miss, attempt 1 of 2): existing self-healing retry
  behavior unchanged — no crash-recovery path involved at all.
- Failure case (Silver-normalization throws on attempt 1 of 2): status resets to
  re-triggerable; a subsequent trigger with `skipSuccessGuard: true` produces a genuine
  new attempt (attempt 2), not a no-op.
- Failure case (Silver-normalization throws on attempt 2 of 2 — the final allowed
  attempt): status resets, but a subsequent `skipSuccessGuard: true` retrigger correctly
  produces **no new attempt** (S7's cap holds) — document ends in a definitively failed
  state, not a misleadingly retryable one. This is the case most likely to be missed if
  implemented without the explicit test.
- Regression: G5's atomic guard still rejects a second concurrent trigger while the first
  is genuinely in flight — guard behavior byte-for-byte unchanged.
- Regression: a normal (non-recovery) call to `runExtractionPipeline` — no options
  argument — behaves identically to pre-task behavior; `hasAlreadySucceeded` still guards
  every ordinary call path.

**Verification command:**
```bash
./scripts/test_extraction_crash_recovery.sh
```

**Invariant enforcement:** G5 — existing enforcement extended (hardening the recovery path
around an unchanged guard), not a new invariant. S7 — verified unaffected by construction
(see design note above), test case required to confirm rather than assume. Code review
required: confirm the G5 atomic guard is byte-for-byte unchanged, and that
`skipSuccessGuard` defaults to `false` with zero behavior change for any pre-existing
caller of `runExtractionPipeline`.

**Regression classification:** HARNESS-CANDIDATE — directly tied to G5 and S7's
failure-mode coverage; R-005 in `RISK_REGISTER.md` is mitigated by this task.

**UI test spec:** N/A — backend-only.

---

## Task 2.2 — Sequential batch upload loop + registration-failure skip + batch cap

**Description:** Multi-file selection on Upload, processed sequentially (register → await
extraction → next file), capped at 15 files, with a registration failure mid-batch skipped
rather than aborting the batch.

**CC prompt:**
```
In UploadForm.tsx, extend file selection to accept multiple PDFs (currently single-file).
Enforce a maximum of 15 files per batch — reject selection beyond that with a clear message,
no partial batch silently truncated. For the selected batch, process files sequentially,
not in parallel: for each file in order, call registerDocument, then AWAIT that file's
extraction (using Task 2.1's now-safe call site) before starting the next file's
registration. Do NOT fire all N registration+extraction calls concurrently — this is an
explicit, tested requirement, not the default outcome of a naive loop over N files.

If a file's registration fails (not extraction — registration itself, e.g. malformed PDF
input), skip that file and continue the loop to the next file. Do not abort the remaining
batch. Track this outcome distinctly from a successful upload for that file's row state
(Task 2.3 renders it).
```

**Test cases:**
- Happy path: a 5-file batch uploads and extracts all 5, strictly one at a time (no two
  files' extraction calls in flight simultaneously — verifiable via call ordering/timing in
  the test, not just final state).
- Failure case: selecting 16+ files is rejected with a clear message before any upload
  begins; selecting exactly 15 succeeds.
- Failure case: file 3 of a 10-file batch fails registration — files 1–2 succeed normally,
  file 3 is skipped, files 4–10 still process. Batch does not abort.
- Regression: single-file upload (batch of 1) behaves identically to pre-enhancement
  single-file upload.
- Regression (Finding 2, Design Gate): the same file (identical content hash) selected
  twice within one batch — both registration attempts pass through the same
  `registerDocument()` race-tolerant catch path already relied on for concurrent
  duplicates; confirm it also handles this sequential-duplicate case correctly (one
  registers, the other is rejected/flagged as a duplicate, batch continues either way).

**Verification command:**
```bash
./scripts/test_batch_upload_sequencing.sh && npx playwright test ui_tests/upload.spec.ts
```

**Invariant enforcement:** None new — this task's sequencing, cap, and skip-on-failure
rules are task-level acceptance criteria per `ENH-001_SCOPE.md` Section 4, not formal
invariants. G4 (content-hash dedup) is touched implicitly — confirm in code review that
`registerDocument()`'s existing race-tolerant catch block (relied on unchanged, per the
brief's Known Constraints) is not bypassed by the new loop structure.

**Regression classification:** HARNESS-CANDIDATE for the sequencing test
(`test_batch_upload_sequencing.sh` — directly verifies the no-parallel-extraction
acceptance criterion); REGRESSION-RELEVANT for the Playwright extension.

**UI test spec:**
```
Screen: Upload
Test strategy: User-generated — tests drive multi-file selection to create required state
Assertions to implement:
- Multi-file selection accepted up to 15 files
- Selection of 16+ files rejected with visible message, no upload attempted
- Batch of 5 files all reach a terminal (success or failure) row state
- A failed registration mid-batch does not block subsequent files from processing
Test file path: ui_tests/upload.spec.ts (extend existing)
```

---

## Task 2.3 — Per-file progress state UI

**Description:** Each file in a batch shows its own progress state (queued / registering /
extracting / done / failed) as the sequential loop advances through the batch. Also closes
Design Gate Finding 3: Task 1.3's click-through (Session 1) can silently abandon an
in-progress batch if clicked before the batch finishes, since this is entirely
client-side with no backend job queue — navigating away unmounts the loop mid-batch,
with no error shown. Fix: suppress the click-through link for any row until **every** row
in the batch has reached a terminal state (done or failed), not just that row.

**CC prompt:**
```
Add per-file row state to UploadForm.tsx's batch UI, driven by Task 2.2's sequential loop:
each file shows queued -> registering -> extracting -> done, or -> failed (registration
skip from Task 2.2, or extraction failure post-Task-2.1's crash-recovery reset). State
updates as the loop actually progresses through each file in order — a file later in the
queue visibly shows "queued" while an earlier file is still "extracting", not all files
jumping to a final state at once.

Design Gate Finding 3 fix: Task 1.3's per-row click-through to a document's extracted
lines must not render for ANY row until the entire batch has reached a terminal state
(every row is done or failed) — not just the individual row being done. This prevents a
user from navigating away mid-batch and silently abandoning files still in the queue.
Track batch-level completion (all rows terminal) as a single derived boolean gating every
row's click-through visibility, not a per-row-only condition.
```

**Test cases:**
- Happy path: mid-batch, files not yet reached show "queued", the current file shows
  "extracting", completed files show "done" — observable at a specific point during
  processing, not just at batch end.
- Failure case: a skipped (registration-failed) file's row shows "failed", distinct from
  "done".
- Regression: single-file upload still shows correct state progression (queued →
  registering → extracting → done), matching pre-batch behavior in substance if not
  in row-list form.
- Failure case (Finding 3, Design Gate): a completed row's click-through link does NOT
  render while any other row in the same batch is still queued/registering/extracting —
  even though that individual row is done.
- Happy path (Finding 3): once every row in the batch reaches a terminal state, the
  click-through link becomes visible on all completed (done) rows.

**Verification command:**
```bash
npx playwright test ui_tests/upload.spec.ts
```

**Invariant enforcement:** None.

**Regression classification:** REGRESSION-RELEVANT — extends existing `upload.spec.ts`.

**UI test spec:**
```
Screen: Upload
Test strategy: User-generated — tests drive a batch upload and assert intermediate state
Assertions to implement:
- Mid-batch snapshot shows correct mixed states across rows (queued/extracting/done)
- Failed row is visually/textually distinct from done row
- Single-file batch still shows full state progression
- Click-through absent on a done row while any other row in the batch is non-terminal
- Click-through present on all done rows once the whole batch reaches a terminal state
Test file path: ui_tests/upload.spec.ts (extend existing)
```

---

## Task 2.4 — Running success-only toast counter

**Description:** A single toast displaying "X/N uploaded" that updates as each file in the
batch completes successfully — N fixed at batch start, X incrementing only on success.
Built via existing `dismiss()`/`add()` primitives in `toastStore.ts` (M-009); no new
primitive, `ToastProvider.tsx` (M-083) untouched.

**CC prompt:**
```
In UploadForm.tsx's batch loop, track a single running toast across the batch: on batch
start, do not show a toast yet. On the first file's successful completion, call
useToast()'s underlying add() (via toastStore.ts, M-009) with "1/N uploaded" (N = batch
size fixed at start) and store the returned toast id. On each subsequent file's successful
completion, call dismiss(previousId) then add() with the updated "X/N uploaded" text,
storing the new id. Do NOT increment the counter or touch the toast on a failed/skipped
file — X only reflects successes. Do not add any new function to toastStore.ts (M-009) or
ToastProvider.tsx (M-083) — this task only calls existing add()/dismiss() from
UploadForm.tsx.
```

**Test cases:**
- Happy path: a 5-file batch, all succeed — toast text progresses 1/5 → 2/5 → 3/5 → 4/5 →
  5/5, with only one toast visible at any time (never two stacked).
- Failure case: a 10-file batch with 3 registration failures — counter ends at "7/10", not
  "10/10" or "7/7"; failed files do not advance or appear in the counter.
- Regression: `toastStore.ts` (M-009) and `ToastProvider.tsx` (M-083) have zero code
  changes — confirm via diff in code review, not just behavioral test.

**Verification command:**
```bash
npx playwright test ui_tests/upload.spec.ts
```

**Invariant enforcement:** None new — task-level acceptance criteria per
`ENH-001_SCOPE.md` Section 4. Code review required: confirm no changes to
`src/lib/toastStore.ts` or `src/components/ToastProvider.tsx`.

**Regression classification:** REGRESSION-RELEVANT — extends existing `upload.spec.ts`.

**UI test spec:**
```
Screen: Upload
Test strategy: User-generated — tests drive a batch upload and observe toast state
Assertions to implement:
- Toast text updates correctly as each file succeeds (never two toasts stacked)
- Counter denominator fixed at batch size; numerator counts successes only
- Failures do not appear in or advance the counter
Test file path: ui_tests/upload.spec.ts (extend existing)
```

---

## Session Summary

| Session | Tasks | New invariants | Schema change | Claude.md bump |
|---|---|---|---|---|
| 1 — UI Clarity | 1.1–1.4 | None | No | No |
| 2 — Batch Upload | 2.1–2.4 | None (G5 enforcement extended, not new) | No | No |

Confirms `ENH-001_SCOPE.md` Section 6 (Tier 2: Type A, multi-session, no invariant
additions) and Section 7's reconfirmation — 2 sessions, as anticipated. Tier stands.