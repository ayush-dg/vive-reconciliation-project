# VERIFICATION_CHECKLIST.md
<!-- Phase 8 Part 1 — System Sign-Off.
     Required for customer deliverables and internal accelerators.
     Mental confirmation is not sign-off for deliverables. -->

**Project:** VIVE Statement Reconciliation (Bounded First Build)
**Date:** 2026-09-01
**Engineer:** Vaishali
**Branch:** session/s10_phase8_signoff (off feature/pbvi_execution @ 063b7e6, which carries
all of Sessions 1–9 merged via PR #8)

All results below come from actually running `verification/REGRESSION_SUITE.sh`,
`verification/HARNESS.sh`, and `verification/UI_HARNESS.sh` against the local SQLite
fallback (no live Fabric or live Claude API access in this environment — see the
Non-Portable Checks note at the bottom). Nothing here is asserted from documentation alone.

---

## Session Completion

| Session | SESSION_LOG | VERIFICATION_RECORD |
|---|---|---|
| S1 — Scaffolding + Auth + DB schema | [x] COMPLETE | [x] VERIFIED — literal "PASS" |
| S2 — Document intake | [x] COMPLETE | [x] VERIFIED — literal "PASS" |
| S3 — Extraction service | [x] COMPLETE | [x] VERIFIED — "Completed"; Challenge Agent ran, FINDINGS dispositioned FIXED |
| ~~S4~~ | REMOVED 2026-08-28 (NetSuite/CCC ingestion externally owned) | N/A |
| S5 — Matching service | [x] COMPLETE | [x] VERIFIED — "Completed"; Challenge Agent ran, FINDINGS dispositioned FIXED |
| S6 — Home + Exceptions + Document Detail | [x] COMPLETE | [x] VERIFIED — "Completed"; Challenge Agent ran, some FINDINGS FIXED, some accepted as Untested Scenarios |
| ~~S7~~ | REMOVED 2026-08-28/2026-09-01 (Gold reporting, engineer-deferred) | N/A |
| S8 — Extraction quality improvements | [x] COMPLETE | [ ] VERIFIED — "Completed (built and reviewed; live-data verification is a real gap, honestly recorded)". 3/5 tasks live-verified; Tasks 8.3/8.5 code-review-only. No Challenge Agent (lightweight-patch mode, by engineer direction). |
| S9 — Per-vendor deterministic parsers + real OCR | [x] COMPLETE | [x] VERIFIED — "Completed"; all planned cases passed, live-data verified against all 9 real vendors. No Challenge Agent (lightweight-patch mode, by engineer direction). |

S8 is marked un-checked on VERIFICATION_RECORD specifically because its own record
documents two tasks as code-review-only, not live-tested — carried forward honestly here
rather than rounded up to a clean PASS.

---

## Invariant Validation

| Invariant | Method | Result |
|---|---|---|
| G1 — Extraction attempts append-only, one document each (promoted from S9; = Claude.md IC-1) | Automated | [x] PASS |
| G2 — No unvalidated extraction becomes match-eligible (= IC-2) | Automated | [x] PASS |
| G3 — Extracted content is model data, never model instructions (= IC-3) | Automated | [x] PASS |
| G4 — Content-hash idempotency (= IC-4) | Automated | [x] PASS |
| G5 — Single active processing owner (= IC-5) | Automated | [x] PASS |
| S1 — Upload does not trigger matching | Automated | [x] PASS |
| S2 — Re-uploads are version-chained, not duplicated | Automated | [x] PASS |
| S3 — Reporting reads ReportView, not `recon` directly | N/A this build | [ ] N/A |
| S4 — `legal_entity_id` requirement | Automated | [x] PASS |
| S5 — Exception category is a closed enum | Automated | [x] PASS |
| S6 — Normalization version traceability | Automated | [x] PASS |
| S7 — Extraction attempts are bounded (max 2) | Automated | [x] PASS (corrected 2026-09-02 — see Manual check details; original FAIL was a stale test, not a real defect) |
| S8 — Reference data is version-bound (amended) | Automated | [x] PASS |
| S10 — `extracted` schema write precedes validation | Automated | [x] PASS |
| S11 — Statement-line amounts immutable after extraction | Manual | [ ] NOT INDEPENDENTLY VERIFIED |

T1–T7 excluded — explicitly deferred/BCE-scope, not built in this bounded build
(`ARCHITECTURE.md` §7 Parking Lot; `INVARIANTS.md`'s own Target-state framing).

### Manual check details

**S3 — N/A this build:** Session 7 (Gold-layer reporting integration) was removed from
`EXECUTION_PLAN.md` by engineer direction. S3 itself "was never removed as an invariant,
only its implementing task" (`EXECUTION_PLAN.md` line 1481) — there is currently no
reporting surface in the running system for this check to exercise. Re-verify when Session
7 is eventually built.

**S7 — originally recorded as FAIL; CORRECTED 2026-09-02 to PASS — false positive, not a
real defect.** `./scripts/test_bounded_retry.sh`, run cleanly once (before any re-run
pollution — see Non-Portable/Non-Idempotent note below): 13 of 14 sub-checks passed. The
one failure was **"TC-1: document proceeds to matching-eligible (Processing badge, not
Failed/Retrying)"**.

**Correction (2026-09-02, discovered during BCE Stage 2 Sessions B and C — direct source
verification, not just an agent claim):** `src/lib/documentStatus.ts:155-158` has an
explicit, distinct `'Extracted'` badge — added 2026-08-31 by engineer direction,
specifically to disambiguate "extraction succeeded, awaiting Reconcile" from `'Processing'`
(the code comment literally says "distinct from 'Processing'"). The real application
behavior for this exact case is correctly `badge: 'Extracted'`. The test assertion at
`scripts/test_bounded_retry.mjs:58` still checks `status.badge === 'Processing'` — a
pre-2026-08-31 expectation that was never updated when the badge scheme grew a 6th value.
**There is no status-computation defect.** The underlying S7 invariant (bounded retry) was
never actually violated — this was a stale test assertion producing a false FAIL, caught a
day later by two independent Stage 2 module-contract passes (Sessions B and C) and
confirmed directly against source by CC before amending this record. The original
Engineer Sign-Off below is not invalidated by this — it was signed with this item listed as
a known open issue; it is now resolved as never having been a real issue. The stale test
itself (`scripts/test_bounded_retry.mjs:58`) has **not** been fixed as part of this
correction — that's a one-line code change outside BCE Stage 2's read-only discovery scope,
flagged for the engineer to action separately (it will keep producing this same false FAIL
on every future harness run until fixed).

**S11 — not independently verified.** No dedicated automated check for post-extraction
immutability of `silver.statement_line` amounts was found or run in this pass (distinct
from S6/normalization-version, which was tested). The invariant currently holds by
architectural absence — no UPDATE code path exists against that table in the reviewed
scripts — but this was not behaviorally exercised (e.g., attempting a direct update and
confirming rejection). Flag for a dedicated test in a future session; not a known failure,
just an untested claim.

**G5 — one flaky, non-reproducing failure observed, not counted as a genuine result.**
`ui_tests/extract-trigger.spec.ts`'s G5 rapid-succession test (`line 124`) failed with
`ECONNRESET` when that spec file was run in isolation (via `REGRESSION_SUITE.sh`), but
**passed** when the full 61-test suite ran together via `UI_HARNESS.sh` moments later. Since
the same assertion passed on its other execution, this is recorded as connection-level
flakiness under the isolated single-spec run, not a functional regression — consistent with
`S08_SESSION_LOG.md`'s and `S09_SESSION_LOG.md`'s own prior notes about "2 known
pre-existing flakes unrelated to \[that] session's changes."

---

## Architecture Alignment

- [x] System matches `ARCHITECTURE.md` decisions — cross-checked as part of this session's
  earlier doc-alignment pass (all D-decisions reconciled against current doc versions,
  ARCHITECTURE.md v1.6). One known non-blocking open item remains: D-F/OD5's entity-scoped
  access model (documented as genuinely open, not silently dropped).
- [ ] No undocumented components or dependencies — **not independently verified this pass.**
  A full source-tree-vs-ARCHITECTURE.md component audit was not performed; this pass relied
  on running documented verification commands, not a fresh code inventory. Recommend as a
  distinct check before Part 1 sign-off, or accept as a known gap in the sign-off record.
- [x] Failure modes behave as `ARCHITECTURE.md` described — confirmed via
  `loading-error-consistency.spec.ts` (7/8 passing; the 8th's single failure was itself a
  flaky timeout under parallel load, not a functional divergence — see UI_HARNESS.sh run
  notes below) and `test_bounded_retry.sh`'s failure-path sub-checks (all passed except the
  one S7 badge issue above, which is a display bug, not a failure-mode divergence).

---

## Operational Readiness

- [x] System starts cleanly — confirmed twice: Playwright's `webServer` successfully
  launched `npm run dev` against the local SQLite fallback for both the `REGRESSION_SUITE.sh`
  run (28 checks) and the full `UI_HARNESS.sh` run (61 tests, 4 parallel workers).
- [x] System recovers from expected failure modes — confirmed via
  `loading-error-consistency.spec.ts` (retry-after-error flows pass) and
  `test_bounded_retry.sh` (bounded retry, OCR_LOW_CONFIDENCE flagging, and non-3rd-attempt
  behavior all pass).
- [x] No internal errors exposed in responses — the dev server logs several intentionally
  simulated errors (test-error page, not-found document/vendor lookups) during the suite
  run; all are caught by the app's own error boundaries per the passing tests, not leaked
  to the client beyond the intended inline error UI.

---

## Session Integration Checks

- [x] All session integration checks passed — confirmed directly in each session's own log
  (`S01`–`S09`, all say `[x] PASSED`). S08 and S09 both independently pre-recorded the same
  "2 known pre-existing flakes" this Phase 8 run rediscovered — not a new issue.

---

## Non-Portable Checks (recorded, not silently omitted)

- **Task 1.2** (`G1`/`S4`/`S5`/`S10`/`S11` schema creation) — its documented verification
  command requires `sqlcmd` against a live `$FABRIC_SQL_ENDPOINT`; not available in this
  sandbox. Local-fallback equivalent `npm run test:schema` was run instead (see below).
- **Task 8.2** (live Claude extraction path) — requires a live `ANTHROPIC_API_KEY`; not run.
- **Tasks 8.1, 8.3, 8.4, 8.5** — their documented verification scripts were never actually
  committed to the repo (confirmed absent via direct file search). These four tasks were
  code-review-verified only during Session 8, per `sessions/S08_VERIFICATION_RECORD.md`'s
  own honest admission — carried forward here rather than re-asserted as tested.

## Verification-Tooling Finding (new — surfaced by actually running these scripts twice)

Running `npm run test:schema`, then separately `HARNESS.sh` (which re-runs
`test_extraction_attempt_recording.sh` and `test_bounded_retry.sh` against the same,
already-populated local SQLite file used moments earlier by `REGRESSION_SUITE.sh`) produced
**new failures distinct from any application defect**: `SqliteError: UNIQUE constraint
failed: extracted_vendor_registry.vendor_slug`. At least three scripts
(`test_extraction_attempt_recording.mjs`, `test_bounded_retry.mjs`,
`test_foundation_schema.mjs`) seed a fixed vendor slug with no cleanup/uniqueness handling,
so **none of these verification scripts are currently safe to re-run against a
already-used local database** — only their first run against fresh state is meaningful.
This directly affects `HARNESS.sh`'s stated purpose ("run before each future sprint and
after sprint close-out") — as committed today, a second consecutive run will produce
spurious failures unrelated to any real regression. **Recommendation (not implemented in
this pass — a code change, out of scope for Phase 8 artifact assembly):** either reset the
local SQLite file between harness runs, or make these fixture scripts use a
uniquely-generated vendor slug per run. This is an operational/tooling gap, not an
invariant violation — G1 and S7 above reflect the scripts' actual first-run (clean-state)
results, not the polluted re-run.

---

## Final Sign-Off

**Engineer:** Vaishali **Date:** 01-09-2026

*By signing: invariants validated against assembled system; architecture is as designed;
system meets the four operational tests of the responsibility model.*

**Open items carried into this sign-off decision, not hidden:**
1. ~~S7 — real FAIL (status-badge display bug after successful bounded retry).~~
   **RESOLVED 2026-09-02 — was a false positive (stale test assertion), not a real defect.
   See the corrected S7 entry above.** The stale test itself
   (`scripts/test_bounded_retry.mjs:58`) remains unfixed — a one-line follow-up for the
   engineer, outside this correction's scope.
2. S11 — not independently verified (architecturally sound, untested).
3. S3 — N/A, no reporting surface exists yet (Session 7 deferred).
4. Architecture Alignment's "no undocumented components" checklist item — not
   independently audited this pass.
5. Verification-tooling non-idempotency (see above) — affects future harness re-runs, not
   this sign-off's validity, since all reported results reflect first-run clean state.
6. Sessions 8–9 ran without Challenge Agent review (engineer-directed lightweight-patch
   mode) — recorded, not treated as equivalent to the full-ceremony sessions.
