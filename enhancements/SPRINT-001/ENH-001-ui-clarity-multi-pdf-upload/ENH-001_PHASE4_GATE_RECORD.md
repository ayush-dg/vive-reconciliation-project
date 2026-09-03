# ENH-001_PHASE4_GATE_RECORD.md
**Enhancement:** ENH-001
**Engineer:** Vaishali
**Review session:** 2026-09-03 (this conversation)

---

## Section A — Evaluation Criteria

| # | Criterion | Source |
|---|---|---|
| 1 | G4 (content-hash dedup) semantics unchanged | Invariant: G4 |
| 2 | G5 (processing-ownership lock) semantics unchanged except the sanctioned crash-recovery extension | Invariant: G5 |
| 3 | S1 (upload never triggers matching) unaffected | Invariant: S1 |
| 4 | S4 (legal_entity_id required) unaffected | Invariant: S4 |
| 5 | S7 (max 2 extraction attempts) unaffected by the crash-recovery fix | Invariant: S7 |
| 6 | Extraction runs strictly sequentially, never parallel, across a batch | ENH-001_SCOPE.md §4 (task-level acceptance criterion) |
| 7 | A mid-batch registration failure is skipped, not fatal to the batch | ENH-001_SCOPE.md §4 |
| 8 | Toast counter denominator fixed at batch start; numerator success-only | ENH-001_SCOPE.md §4 |
| 9 | No database schema change | ENH-001_BRIEF.md Known Constraints (MANDATORY) |
| 10 | No Claude.md version bump | ENH-001_SCOPE.md §5 |

---

## Section B — Requirements Traceability

| Requirement | Component | Task | Coverage Rating |
|---|---|---|---|
| Status label renames | `HomeView.tsx` | 1.1 | FULLY MET |
| Combined summary + drop Confidence/Provider columns | `DocumentDetailView.tsx` | 1.2 | FULLY MET |
| Upload → extracted-lines click-through | `UploadForm.tsx` | 1.3 | PARTIALLY MET — see Finding 3 below |
| Upload time in IST | `HomeView.tsx`, `DocumentDetailView.tsx` | 1.4 | FULLY MET |
| Multi-PDF selection, sequential, capped at 15 | `UploadForm.tsx` | 2.2 | FULLY MET |
| Crash-recovery fix (IC-CANDIDATE-01) | `extraction.ts` | 2.1 | PARTIALLY MET — see Finding 1 below |
| Per-file progress state | `UploadForm.tsx` | 2.3 | FULLY MET |
| Running success-only toast counter | `UploadForm.tsx`, reuses `toastStore.ts` | 2.4 | FULLY MET |
| Registration failure skipped, not fatal | `UploadForm.tsx` | 2.2 | FULLY MET |

---

## Section C — Adversarial Stress Test Findings

### Finding 1 — EXECUTION — Task 2.1's target scenario is mis-scoped

Read `extractionPipeline.ts` directly rather than assuming the "any thrown failure"
framing in Task 2.1's original CC prompt was accurate. It isn't, and the difference
matters for what gets built and tested.

`runExtractionPipeline`'s per-attempt work (`identifyAndExtract`, `validateExtraction`) is
already wrapped in its own internal `try/catch` — a failure there is caught, an attempt
row is still written (S10), and the loop either retries or returns normally. **This path
never throws out of the function.** The actual gap is narrower: the **only** place the
function throws past its own internal handling is when extraction succeeds and validates,
but the subsequent `normalizeToSilver()` call fails — that error is deliberately
re-thrown with context (the code comment explains why: the attempt row is already
correctly written, but the failure "must not vanish as an unhandled rejection"). There's
also a second, minor throw path: `if (!document) throw` at the top, for a not-found
`documentId` — a data-integrity edge case, not really what IC-CANDIDATE-01 was worried
about, but technically also unguarded.

As written, Task 2.1's test case ("runExtractionPipeline throws") is vague enough that an
implementer could mock a generic extraction failure — which would never actually exercise
the crash-recovery path at all, since that case already resolves normally. The fix and its
tests need to specifically target the Silver-normalization-throws-after-successful-
validation scenario.

**Severity:** HIGH — as written, this task could pass its own tests while not actually
covering the real gap it exists to fix.

### Finding 2 — DATA — sequential in-batch duplicates untested

The brief's G4 constraint was verified against `documents.ts`'s race-tolerant catch block
for *concurrent* duplicate registration. A sequential batch introduces a different case:
the same file (same content hash) selected twice in one batch, submitted one after another,
not concurrently. Almost certainly the existing unique-constraint catch handles this too —
a race-tolerant implementation is a strict superset of a sequential-duplicate-tolerant one
— but Task 2.2 has no explicit test case confirming it, and it's a genuinely plausible user
action (accidentally selecting the same PDF twice in a multi-select dialog).

**Severity:** LOW — very likely already handled, but currently unverified and easy to add.

### Finding 3 — ARCHITECTURE vs PLAN GAP — Task 1.3's click-through can abandon an in-progress batch

Task 1.3 (Session 1) renders a click-through once a file's extraction completes. In
Session 2's batch context (Task 2.3 adds per-row state), a file can complete — and show
its click-through — while other files in the same batch are still sequentially processing.
Since this is entirely client-side (Task 2.2's loop runs in the browser, no backend job
queue per the brief's explicit rejection of one), clicking that link navigates away from
Upload and, unless something specifically prevents it, unmounts `UploadForm` — silently
abandoning the rest of the batch with no resume mechanism.

Neither Task 1.3 nor any Session 2 task currently addresses this interaction. It wasn't
visible when Task 1.3 was scoped (Session 1, no batch context yet) or when Session 2's
tasks were scoped (each written per-concern, not against Task 1.3's cross-session
interaction).

**Severity:** HIGH — silent data loss from the user's perspective (files simply never
finish uploading, no error shown) is a worse failure mode than an explicit error would be.

**Recommendation:** Needs an explicit decision, not a default. Options: (a) suppress the
click-through while a batch has files still in progress, only showing it once the whole
batch reaches a terminal state; (b) allow navigation but warn the user first
(`beforeunload`-style or an in-app confirm); (c) accept it as a known limitation and
document it. (a) is the smallest change and doesn't lose any interactivity that matters
until the batch is actually done, so it's my instinct — but that's a process recommendation,
not something to implement without your confirmation.

---

## Section D — Risk Register with Dispositions

| # | Finding | Severity | Requirement/Invariant Affected | Return to Phase | Recommendation | Disposition | Rationale |
|---|---|---|---|---|---|---|---|
| 1 | Task 2.1 targets the wrong failure scenario | HIGH | IC-CANDIDATE-01 / R-005 fix | Phase 3 | Rewrite Task 2.1's CC prompt and test cases around the Silver-normalization-throw path specifically | **RESOLVE** | Task 2.1 rewritten in `ENH-001_EXECUTION_PLAN.md` (Option B): distinguishable `SilverNormalizationFailure` error type in `extractionPipeline.ts` (M-022), `skipSuccessGuard` opt-in bypass of `hasAlreadySucceeded` for the recovery path only, zero behavior change for any existing caller. S7 interaction verified safe by construction (loop's own MAX_ATTEMPTS bound), added as an explicit test case rather than assumed. New touch point: M-022, previously not in `ENH-001_BRIEF.md`/`ENH-001_SCOPE.md`. |
| 2 | No sequential in-batch duplicate test | LOW | G4 | Phase 3 | Add one test case to Task 2.2 | **RESOLVE** | Added to Task 2.2's test cases in `ENH-001_EXECUTION_PLAN.md` — same file selected twice in one batch, verifying the existing race-tolerant registration catch also covers this sequential case. |
| 3 | Click-through can abandon an in-progress batch | HIGH | Requirements — batch upload reliability | Phase 3 | Add explicit handling (suppress click-through during active batch) | **RESOLVE** | Task 2.3 amended in `ENH-001_EXECUTION_PLAN.md`: click-through suppressed on every row until the whole batch reaches a terminal state (all rows done or failed), not just the individual row. Task 1.3 cross-referenced to note the Session 2 dependency. |

**Overall verdict:** All three findings RESOLVE-dispositioned with concrete plan changes
already made. Ready for re-review confirmation — see below.

**Re-review note:** Task 2.1's rewrite introduces a genuinely new touch point —
`extractionPipeline.ts` (M-022) — that wasn't in `ENH-001_BRIEF.md`'s or
`ENH-001_SCOPE.md`'s Known Touch Points. Both need a one-line addition before this gate
closes; not a re-run of the full brief review gate (Prompt 1 already passed and the
underlying enhancement scope hasn't changed), just an addition to keep BCE legibility
accurate for Phase 3 onward.

**Top 3 blockers:** None. M-022 touch-point addition (above) completed 2026-09-03 in both
`ENH-001_BRIEF.md` and `ENH-001_SCOPE.md` — no longer pending.
**Confidence level:** 92% — the S7-safety-by-construction claim for Task 2.1 is a design
argument verified against source, not yet verified by a passing test (that happens at
Phase 6/7); everything else is either direct source verification or a scoped, narrow fix.

*(Per methodology: I may not declare this gate passed. The verdict above is this review's
output, not a gate-pass declaration. Only you sign off, below.)*

---

## Section E — Invariant Ownership Check (existing invariants touched, no new ones)

No new invariants this enhancement — Step 2b's full failure-mode review doesn't apply.
Lightweight ownership check on the five existing invariants this enhancement touches:

1. Can you state, without opening any document, what G5's atomic guard actually is and why
   Task 2.1's fix must not touch it?
2. Can you state why S7's attempt-count logic (`getExistingAttemptCount`, recalculated from
   the DB) means a crash-and-retry cycle can't accidentally exceed 2 attempts?
3. Can you state why the toast counter's failure semantics (Finding-adjacent, not itself an
   invariant) don't interact with S1 or S4 at all?

**Engineer answers:** PASS

---

## Section F — UI Surface Review

**Applies** — this enhancement touches Home, Upload, and Document Detail.

| Check | Finding | Severity | Recommendation | Disposition |
|---|---|---|---|---|
| Screen coverage | All three touched screens (Home, Upload, Document Detail) have owning tasks | INFO | None needed | ACCEPT |
| Cross-task interaction on Upload | See Finding 3 — Task 1.3's click-through vs. Task 2.2/2.3's in-progress batch | HIGH | See Section D disposition | *(engineer to disposition)* |
| Toast/global element reuse | Task 2.4 correctly scopes to zero changes in `ToastProvider.tsx`/`toastStore.ts` beyond calling existing methods — verifiable by diff at task sign-off | INFO | None needed, already built into Task 2.4's verification | ACCEPT |

**Step 1c verdict:** Same HIGH finding as Section D Finding 3 — not independently blocking
beyond what's already tracked there.

---

## Engineer Sign-Off

**Step 1 gate:** All three findings dispositioned RESOLVE with concrete plan changes made
(see Section D) — Findings 1 and 3 (HIGH) resolved via `ENH-001_EXECUTION_PLAN.md` rewrites
(Task 2.1 Option B redesign; Task 2.3 click-through suppression). Finding 2 (LOW) resolved
via an added test case. M-022 (surfaced by Task 2.1's rewrite) added as a new touch point
in both `ENH-001_BRIEF.md` and `ENH-001_SCOPE.md` — not a re-run of Prompt 1/2, just a
BCE-legibility addition. No process items remain.
**Section E ownership check:** PASS — all three questions answered correctly
**Signature:** Vaishali
**Date:** 03-09-2026