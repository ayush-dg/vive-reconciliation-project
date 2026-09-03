**Session:** ENH-001 Session 1 — UI Clarity Fixes
**Date:** 2026-09-03
**Engineer:** Vaishali

## Task 1.1 — Status label renames

### Test Cases Applied
Source: ENH-001_EXECUTION_PLAN.md Session 1

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Document with `status_badge = 'Extracted'` | Renders label "Extraction success" | WRITTEN — 1 assertion (new test) | PASS |
| TC-2 | Document with `status_badge = 'Reconciled'`, no open exceptions | Renders "Recon done" | WRITTEN — 1 assertion (updated existing test) | PASS |
| TC-3 | Document with `status_badge = 'Reconciled'` and open exceptions | Still renders "Recon done" with exceptions link, unaffected by rename | WRITTEN — 2 assertions (updated existing test) | PASS |

### Prediction Statement
N/A — Autonomous mode, no prediction discipline.

### Challenge Agent Output
**Note on mechanism:** `./tools/challenge.sh` invokes `claude --print` as a subprocess,
which is not available as a nested CLI call inside this build environment. Substituted
with a fresh subagent given the identical evidence package (Claude.md, INVARIANTS.md,
Task 1.1 spec, code diff, verification results) and the exact same challenge prompt —
same no-prior-context constraint as the script's isolated `claude --print` invocation.

**Verdict:** FINDINGS (2 items) — both dispositioned TEST, both now passing.

**Untested scenarios (from challenge agent):**
1. No assertion checked `badgeClass` post-rename — the CC prompt's "do not change
   badgeClass" constraint was unenforced by the test suite. (NONE invariant at risk.)
2. TC-3's spec wording ("Reconciled" + open exceptions) vs. the code path actually
   exercised (`'Failed'` + open exceptions) — flagged as a spec/implementation wording
   gap, not a code defect (the `'Reconciled'` branch is unconditional, `open_exception_count`
   is irrelevant to it as written).

**Unverified assumptions (from challenge agent):**
1. JSDoc comment above `homeDisplayStatus` still quoted the pre-rename strings verbatim —
   factually stale documentation in the touched file. (Testable: YES.)
2. `'Reconciled'` + `open_exception_count > 0` assumed unreachable in practice (exceptions
   only ever surface via the `'Failed'` badge per `documents.ts`'s own comment) — not
   independently tested here. (Testable: NO — would require forcing an inconsistent
   DB/status state outside this task's normal upload→extract→match flow.)

**Invariant coverage gaps:** NONE — task touches no IC-1..5/CQ-001 enforcement point.

**Scope boundary observations:** None — diff confined to the two files declared in scope.

**Finding dispositions:**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
| 1 (stale JSDoc) | TEST | Updated the comment's quoted strings to "Extraction success"/"Recon done", noted the 2026-09-03 rename. No logic touched. | Re-ran `npx playwright test ui_tests/home.spec.ts` — 8/8 PASS |
| 2 (no badgeClass assertion) | TEST | Added `toHaveClass(/extracted/)` and `toHaveClass(/reconciled/)` assertions to the "Extraction success" and "Recon done" (reconcile) tests. | Re-ran `npx playwright test ui_tests/home.spec.ts` — 8/8 PASS, including the 2 new class assertions |

Assumption #2 above (Reconciled+exceptions unreachability) is noted as an out-of-scope
observation for the session log, not actioned in this task — forcing that state requires
infrastructure beyond Task 1.1's declared scope.

### Code Review
No invariant touches this task — display-string change only (per Task 1.1's own
"Invariant enforcement: None"). No code review section required.

### Scope Decisions
No scope decisions — task executed exactly as specified in `ENH-001_EXECUTION_PLAN.md`.
Two existing test assertions (`home.spec.ts` lines 89, 110 pre-edit) referencing the old
`'Done'` label were updated to `'Recon done'` since they would otherwise regress — this is
within Task 1.1's own declared regression test case, not scope creep.

### BCE Impact
M-068 (`HomeView.tsx`) touched — string literal change only, no change to the module's
purpose, interface, or callers. No `MODULE_CONTRACTS.md` field changes.

| Artifact | Field | Change |
|---|---|---|
| MODULE_CONTRACTS.md | M-068 description | No change — label text is not part of the documented contract |

### Verification Verdict
[x] All planned cases passed
[x] Challenge agent run — verdict recorded (CLEAN or FINDINGS) — FINDINGS (2), both TEST-dispositioned
[x] All FINDINGS dispositioned — ACCEPT with rationale or TEST with result
[x] Pre-commit declaration recorded — see below
[x] Code review complete (if invariant-touching) — N/A, no invariant touched
[x] Scope decisions documented

**Status:** COMPLETE. All verification cases PASS (8/8, including 2 challenge-driven
additions). Ready to commit.

### Pre-Commit Declaration
**Functions touched:** `homeDisplayStatus()` in `HomeView.tsx` (2 string literals + JSDoc
comment text; no branching/logic change).
**Schemas touched:** None.
**Config touched:** None.
**Files touched:** `src/app/(app)/home/HomeView.tsx`, `ui_tests/home.spec.ts` — both within
declared blast radius (Pre-Build Validation, Session Log).
**Scope confirmed:** YES — within `docs/Claude.md` Section 3 (`/src/**`, `/ui_tests/**`).

---

## Task 1.2 — Document Detail: combined summary + drop two columns

### Pre-Task Finding
On inspection, the "combine extraction and reconciliation summary" requirement was
**already satisfied** in the existing code before this task began — the "Extracted lines
(N total)" heading and "Reconciliation complete — X matched, Y exceptions" line were
already rendered in the same panel container (`documentDetail.ts` already assembles
`reconciliation` counts; likely already fixed during the S6→S8 lightweight-patch UI
redesign, per `PROJECT_MANIFEST.md`'s note on that gap). No code change made for this
part — a test was added to confirm the existing behavior instead of building a no-op.
Same pattern as the badge-fix item found already resolved elsewhere in this enhancement.
The only actual code change: removing the Confidence and Provider columns from the table.

### Test Cases Applied
Source: ENH-001_EXECUTION_PLAN.md Session 1

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Document Detail rendering | One combined summary block (already existing), not two separate ones | WRITTEN — 3 assertions (new test, strengthened post-challenge to assert DOM containment) | PASS |
| TC-2 | Extracted-lines table | Renders without Confidence and Provider columns | WRITTEN — 4 assertions (new test) | PASS |
| TC-3 | `documentDetail.ts` data layer | `confidence`/`providerUsed` still returned (UI-only removal) | WRITTEN — 3 assertions (new test, added post-challenge — see Finding 1 below) | PASS |
| TC-4 | Extraction-method summary block | Still renders correctly, unaffected by column removal | WRITTEN — reused existing provider-count assertion within TC-2's test | PASS |
| TC-5 | Other columns/summary values | Unaffected | Covered by pre-existing tests (Invoice Ref/Amount columns, exception count, status badge) — all still pass | PASS |

### Prediction Statement
N/A — Autonomous mode.

### Challenge Agent Output
Same mechanism note as Task 1.1 (fresh context-free subagent substituting for
`./tools/challenge.sh`'s `claude --print` call).

**Verdict:** FINDINGS (2 items) — both dispositioned TEST, both now passing.

**Untested scenarios (from challenge agent):**
1. The task spec's own data-assembly regression case (`confidence`/`providerUsed` still
   returned by `documentDetail.ts`) had no assertion anywhere — the claim that provider-
   summary tests covered it was checked and found incorrect (different function/query).
2. The "renders together in one block" test only asserted independent visibility of two
   text fragments, not DOM containment — couldn't actually detect a regression that
   re-separated the two summaries into different panels.

**Unverified assumptions (from challenge agent):**
1. Ambiguity flagged between the CC prompt's "extraction summary" (the thing to combine)
   and the DOM's separately-labelled "Extraction summary" panel (`extraction-summary-strip`,
   the provider-breakdown block, Task 3.5) which the same CC prompt says is unaffected.
   Resolved by re-reading the brief's own worked example ("Extracted lines (273 total)"
   next to "Reconciliation complete...") — confirms "extraction summary" means the line-count
   heading, not the provider-breakdown panel. The strengthened containment test (Finding 2
   fix) now verifies this reading is correct by construction.
2. Comment claiming data-layer coverage was factually wrong (`getExtractionMethodSummary`
   and `getStatementLinesForDocument` are separate functions/queries) — corrected.

**Invariant coverage gaps:** NONE — presentation-layer only.

**Scope boundary observations:** None — diff confined to declared files.

**Finding dispositions:**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
| 1 (no data-layer regression test) | TEST | Added a new test hitting `/api/documents/:id/detail` directly, asserting `lines[0].confidence`/`providerUsed` are present and correctly typed. Corrected the inaccurate comment that claimed this was already covered. | PASS |
| 2 (no DOM containment check) | TEST | Strengthened the combined-summary test to scope both assertions inside `page.locator('.panel', { has: reconciliation-progress testid })` — genuine containment, not just co-presence on the page. | PASS |

### Code Review
No invariant touched — presentation-layer only, confirmed by inspection (no change to
`documentDetail.ts`'s data assembly, per the task's own constraint).

### Scope Decisions
The "combine summary" instruction was found already satisfied by existing code — treated
as a verified pre-existing state, not re-implemented or forced into a redundant rewrite.
Documented rather than silently claimed as new work.

### BCE Impact
M-013 (`documentDetail.ts`) — not modified. M-076 (`DocumentDetailView.tsx`) — UI-only
column removal, no interface/contract change.

| Artifact | Field | Change |
|---|---|---|
| MODULE_CONTRACTS.md | M-076 description | No change — table column display is not part of the documented contract |

### Verification Verdict
[x] All planned cases passed (10/10, including 1 flaky parallel-worker failure confirmed
    non-reproducing on isolated re-run — not a regression)
[x] Challenge agent run — verdict recorded — FINDINGS (2), both TEST-dispositioned
[x] All FINDINGS dispositioned — ACCEPT with rationale or TEST with result
[x] Pre-commit declaration recorded — see below
[x] Code review complete — N/A, no invariant touched
[x] Scope decisions documented

**Status:** COMPLETE. Ready to commit.

### Pre-Commit Declaration
**Functions touched:** None modified (JSX table structure only — no function signature or
logic change in `DocumentDetailView.tsx`).
**Schemas touched:** None.
**Config touched:** None.
**Files touched:** `src/app/(app)/documents/[id]/DocumentDetailView.tsx`,
`ui_tests/document-detail.spec.ts` — both within declared blast radius.
**Scope confirmed:** YES.

---

## Task 1.3 — Click-through from Upload to a document's extracted lines

### Design Note
The CC prompt's framing ("once extraction completes") maps to 3 of the app's 6
`status_badge.badge` values that are only reachable after a successful extraction:
`'Extracted'`, `'Reconciling'`, `'Reconciled'`. The 4th relevant value, `'Failed'`, is
ambiguous by itself — `documents.ts`'s own `ApiDocument` doc comment confirms it covers
both a genuine extraction failure (no lines exist) and a reconciliation exception
(extraction succeeded, lines exist, matching found a discrepancy). Used the same
`open_exception_count` field Home's own display mapping already uses to disambiguate:
click-through shows for `'Failed'` only when `open_exception_count > 0`.

### Test Cases Applied
Source: ENH-001_EXECUTION_PLAN.md Session 1

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Single-file upload, extraction completes (`'Extracted'`) | Click-through link appears, navigates to Document Detail | WRITTEN — 4 assertions (new test) | PASS |
| TC-2 | Extraction still in progress (`'Processing'`, synthesized via direct DB state — see Deviations) | No click-through shown | WRITTEN — 2 assertions (new test) | PASS |
| TC-3 | Extraction genuinely fails, exhausted retries (`'Failed'`, `open_exception_count === 0`) | No click-through shown | WRITTEN — 3 assertions (new test, strengthened post-challenge to assert `open_exception_count` directly) | PASS |
| TC-4 (added, beyond literal CC prompt scope) | Reconciliation exception (`'Failed'`, `open_exception_count > 0`) | Click-through DOES show — lines genuinely exist | WRITTEN — 5 assertions (new test, added post-challenge — Finding 1) | PASS |

### Prediction Statement
N/A — Autonomous mode.

### Challenge Agent Output
Same mechanism note as Tasks 1.1/1.2 (fresh context-free subagent).

**Verdict:** FINDINGS (1 item) — dispositioned TEST, now passing.

**Untested scenarios (from challenge agent, informational — not all promoted to Verdict
Findings requiring disposition):**
1. **[Promoted to Finding 1]** `Failed` + `open_exception_count > 0` branch never exercised
   as true — the exact case the design note above was written to handle.
2. `'Reconciling'`/`'Reconciled'` badge states not independently pinned in a dedicated test
   (the happy-path test doesn't assert which of the three "show" badges it landed on).
3. `'Retrying'` badge's implicit "no link" fallthrough not independently tested.
Items 2–3 not actioned this task — same conditional already proven correct by construction
via TC-1/TC-2/TC-4 covering the boundary cases; noted as residual, non-blocking coverage
gaps rather than disposed findings (challenge agent's own verdict named only 1 Finding
requiring disposition).

**Unverified assumptions (from challenge agent):**
1. The "no click-through on failure" test asserted only the badge label text, never
   `open_exception_count` directly — couldn't distinguish "correctly hid link" from
   "accidentally hid link via an unrelated bug." Fixed — see Finding disposition.

**Invariant coverage gaps:** IC-2 — the `open_exception_count > 0` branch (encoding
"structurally/arithmetically valid extraction with lines that exist") had zero coverage.
Closed by the new TC-4 test.

**Scope boundary observations:** None — diff confined to declared files.

**Finding dispositions:**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
| 1 (Failed+exception "show" branch untested) | TEST | Added TC-4: uploads, extracts, and runs matching with no NetSuite row seeded (genuine reconciliation exception, not extraction failure) — confirms `open_exception_count > 0` and the click-through IS visible and navigates correctly. Also strengthened TC-3 to assert `open_exception_count === 0` directly via the API response, not just the badge label text. | PASS |

### Code Review
No invariant enforcement point touched — the click-through is read-only navigation, no
state mutation. `open_exception_count` is read, not written.

### Scope Decisions
Extended beyond the CC prompt's literal binary framing (its own "once extraction
completes" wording didn't anticipate the `Failed`-badge ambiguity) after reading
`documents.ts`'s own doc comment on `open_exception_count` — reusing an existing,
documented disambiguation mechanism rather than inventing a new one or leaving the
reconciliation-exception case silently broken.

### BCE Impact
M-070 (`UploadForm.tsx`) — new `Link` import, no interface/contract change. No new touch
point beyond what's declared (`open_exception_count` was already part of `ApiDocument`).

| Artifact | Field | Change |
|---|---|---|
| MODULE_CONTRACTS.md | M-070 description | No change — click-through is a UI addition, not a contract change |

### Verification Verdict
[x] All planned cases passed (10/10 relevant to this task, across repeated runs; 1
    pre-existing unrelated test intermittently fails due to the documented M-011 N+1
    issue at current local-DB size — see Deviations, not a regression from this diff)
[x] Challenge agent run — verdict recorded — FINDINGS (1), TEST-dispositioned
[x] All FINDINGS dispositioned — ACCEPT with rationale or TEST with result
[x] Pre-commit declaration recorded — see below
[x] Code review complete — N/A, no invariant touched
[x] Scope decisions documented

**Status:** COMPLETE. Ready to commit.

### Pre-Commit Declaration
**Functions touched:** None modified (JSX-only addition — new conditional `Link` render
inside the existing Action column, no function signature change).
**Schemas touched:** None.
**Config touched:** None.
**Files touched:** `src/app/(app)/upload/UploadForm.tsx`, `ui_tests/upload.spec.ts` — both
within declared blast radius.
**Scope confirmed:** YES.
