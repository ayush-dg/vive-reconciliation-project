# ENH-001_VERIFICATION_CHECKLIST.md
<!-- Phase 8 Part 1 — Enhancement Sign-Off, Sign-Off Tier 2 (ENH-001_SCOPE.md §6).
     Tier 2 scope: changed invariants only, not a full system sweep. -->

**Enhancement:** ENH-001 — UI clarity fixes + multiple PDF upload
**Sprint:** SPRINT-001
**Engineer:** Vaishali
**Branch:** session/s2_batch_upload (off feature/pbvi_execution, which carries Session 1
merged via PR #10)
**Date:** 2026-09-04

Per `ENH-001_SCOPE.md` §6, this checklist is scoped to G5 (the only invariant with an
actual enforcement-point change — a hardening, not a new mechanism) plus S1/S4/S7
spot-checks (touched by the batch-upload surface but not intended to change). G4 is
declared TOUCHES in `ENH-001_SCOPE.md` §5 but explicitly unmodified (content-hash dedup
logic itself untouched) — included here for completeness, not because its enforcement
changed.

All results below are drawn from tests actually run against the assembled system during
Session 2's own build and Session Integration Check (`S2_VERIFICATION_RECORD.md`,
`S2_SESSION_LOG.md`) — not re-asserted from documentation alone. Where a result was
observed with a caveat during Session 2, that caveat is carried forward here, not
smoothed over.

---

## Invariant Validation

| Invariant | Change | Method | Result |
|---|---|---|---|
| G5 — Single active processing owner | ENFORCES (extended) — Task 2.1's crash-recovery fix adds a `finally`-block status reset (`'processing'` → `'registered'`) around the existing lock's call site when a Silver-normalization failure or exhausted-recovery error occurs; the lock mechanism itself is unchanged | Automated — `scripts/test_extraction_crash_recovery.sh` | [x] PASS — TC-4 (`triggerExtraction` reports ok, recoverable; status resets to `'registered'` after a Silver failure, not stuck at `'processing'`), TC-5 (a trigger while genuinely processing is rejected, not re-queued — the underlying lock guard itself is unaffected by the new finally-block), TC-6 (status also resets to `'registered'` after an *exhausted* recovery, not just a recoverable one) all passed. 20/20 assertions in this script passed before a stale-fixture collision unrelated to this invariant (see Non-Portable/Non-Idempotent note below) |
| S7 — Extraction attempts are bounded (max 2), unaffected | TOUCHES — per-file retry logic itself unchanged by batch sequencing; the crash-recovery fix explicitly does NOT grant a 3rd attempt when the bound is already reached | Automated — `scripts/test_extraction_crash_recovery.sh` TC-3 | [x] PASS — "the exhausted recovery retry throws, not silently returns"; "the thrown error is specifically `RecoveryAttemptsExhausted`"; "no 3rd attempt row was written — S7's bound still holds" |
| S1 — Upload never triggers matching, unaffected | TOUCHES — batch upload is a new caller of registration + extraction, but never calls the matching endpoint | Code review + regression | [x] PASS — `registerFile`/`extractAndTrack` (`UploadForm.tsx`) and `runBatchUploadSequenced` (`batchUploadSequencing.ts`) call only `/api/documents` (register) and `/api/documents/:id/extract`; no code path in Session 2's diff calls `/api/documents/:id/match`. Confirmed by code review of the full diff (Tasks 2.1–2.4), not a dedicated new automated assertion — no batch test exercises reconciliation, consistent with S1 holding by construction |
| S4 — `legal_entity_id` required on registration, unaffected | TOUCHES — batch upload registers N files instead of 1, each still requires a `legal_entity_id` | Automated — `ui_tests/upload.spec.ts` (batch tests) + code review | [x] PASS — `registerFile` sets `body.set('legalEntityId', DEFAULT_LEGAL_ENTITY_ID)` unconditionally for every file in a batch (`UploadForm.tsx`); every batch test in `upload.spec.ts` (5-file, 10-file, duplicate-in-batch) registers successfully through this same fixed path, and the pre-existing legal-entity-mismatch test (single-file) still passes, confirming the requirement itself is untouched |
| G4 — Content-hash idempotency, unmodified (included for completeness only) | TOUCHES — batch registration is a new caller of `registerDocument()`, dedup logic itself not modified | Automated — `ui_tests/upload.spec.ts` ("the same file selected twice within one batch is handled as a duplicate, batch continues (G4)") | [x] PASS — same content hash within one batch registers exactly once; `registerDocument()`'s own dedup logic (the `content_sha256` UNIQUE constraint and pre-check) was not touched by any Session 2 diff |

---

## Architecture Alignment

- [x] No undocumented components introduced — Session 2 added one new module
  (`src/lib/batchUploadSequencing.ts`, a pure sequencing function) and one new client-side
  ref (`batchToastRef`) plus supporting types (`BatchFile`, `BatchRowState`, `BatchRow`),
  all local to `UploadForm.tsx` — recorded in `S2_VERIFICATION_RECORD.md`'s BCE Impact
  notes per task; no schema, integration-point, or architecture-decision change.
- [x] Failure modes behave as designed — confirmed via the full Session 2 test suite
  (26/26 `upload.spec.ts` isolated, 20/20 `home.spec.ts`+`document-detail.spec.ts`
  regression) and the two post-sign-off hotfixes' own verification (10/10
  `document-detail.spec.ts`, 10/10 `home.spec.ts` regression after commit `7255288`).

---

## Session Integration Check

- [x] Session 2's own integration check PASSED — `S2_SESSION_LOG.md` Session Completion,
  signed off by the engineer 04-09-2026. One pre-existing, unrelated bug
  (`loading-error-consistency.spec.ts`'s self-poisoning fixture) was found and root-caused
  during that check, confirmed outside this enhancement's blast radius, not fixed here.

---

## Non-Portable / Non-Idempotent Checks (recorded, not silently omitted)

Same known gap as Session 1/S08/S09 and the greenfield `VERIFICATION_CHECKLIST.md`:
`scripts/test_extraction_crash_recovery.sh` is not safe to re-run against an
already-used local SQLite file — a second consecutive run collides on a fixed vendor
slug (`UNIQUE constraint failed: extracted_vendor_registry.vendor_slug`). All PASS
results above reflect the script's clean first-run state (20/20 assertions passed before
the later, unrelated fixture collision), not a polluted re-run. Not fixed as part of this
checklist — an existing, already-tracked operational/tooling gap, not an invariant
violation.

---

## Final Sign-Off

**Engineer:** Vaishali
**Date:** 04-09-2026

*By signing: the invariants in scope for this Tier 2 enhancement have been validated
against the assembled system; no invariant enforcement point regressed; architecture
alignment holds.*

**Open items carried into this sign-off decision, not hidden:**
1. `scripts/test_extraction_crash_recovery.sh`'s stale-fixture non-idempotency (above) —
   pre-existing, already tracked, not fixed here.
2. `loading-error-consistency.spec.ts`'s self-poisoning fixture bug (found during Session
   2's integration check) — pre-existing, outside ENH-001's blast radius, not fixed here.
3. The two post-sign-off hotfixes (`S2_SESSION_LOG.md` "Post-Sign-Off Hotfixes") are
   outside ENH-001's declared scope and blast radius and are not evaluated against these
   invariants — neither touches G4/G5/S1/S4/S7.
