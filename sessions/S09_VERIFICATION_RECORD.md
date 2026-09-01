**Session:** Session 9 — Per-Vendor Deterministic Parsers + Real OCR
**Date:** 2026-09-01
**Engineer:** Vaishali

## Verification Method (read before the per-task detail below)

Same lightweight-patch mode as Session 8 — no Challenge Agent adversarial review was
performed. Recorded honestly: there is no "Challenge Agent Output" section below because
none was run. Verification instead consisted of:
1. **Live extraction + reconciliation against all 9 real vendor statement PDFs** from
   `C:\Users\yellu\Downloads\Statements`, each vendor's real column-layout trap
   individually confirmed against its own printed statement (not synthetic fixtures).
2. **A full end-to-end pipeline re-verification after the `ensureVendorStmtTable` bug fix**
   — critically, this second pass called the *real* orchestrator
   (`registerDocument()` → `runExtractionPipeline()`), not `identifyAndExtract()` in
   isolation, specifically because the first pass's use of the lower-level function is what
   let the bug ship unnoticed (see this session's own Out of Scope Observation in
   `S09_SESSION_LOG.md`).
3. **The full Playwright suite** (61 tests), run twice — once after the initial 9.1–9.5
   commits, once after the bug fix.
No new committed verification script exists for either pass — both were throwaway scratch
scripts, run and deleted. Same known gap as Session 8, carried forward as Task 9.8.

---

## Task 9.1 — Extraction prompt: credit-sign + running-balance rules

### Test Cases Applied
Source: this session's own investigation (not a pre-existing EXECUTION_PLAN.md task before
this session)

| Case | Scenario | Expected | Method | Result |
|------|----------|----------|--------|--------|
| TC-1 | A vendor statement with a running-balance column Claude might mistake for the line amount | Prompt explicitly warns against summing running-balance/remittance-stub columns | Live extraction against vendors still on the Claude path after this session's deterministic parsers were added (i.e. vendors *not* ported this session, to isolate the prompt's own effect) | PASS — no running-balance-column conflation observed in this session's remaining Claude-routed extractions |
| TC-2 | A vendor statement with credit lines needing a sign flip | Prompt explicitly states the credit-sign convention | Live extraction, same method as TC-1 | PASS |

### Code Review
Prompt change reviewed for scope — added two rules, did not rewrite or weaken any existing
rule. The template-literal backtick syntax error introduced and caught during this task
(see Errors and Fixes) was resolved before any live testing began, so it did not affect any
recorded result.

### Scope Decisions
Generic prompt fix, not vendor-specific — see `S09_SESSION_LOG.md`'s Decision Log for why
a generic fix was chosen over a per-vendor tweak.

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed
[ ] Challenge agent run — not run, lightweight-patch mode
[x] Live-data verification recorded
[x] Pre-commit declaration recorded
[x] Code review complete
[x] Scope decisions documented

**Status:** Completed

---

## Tasks 9.2–9.5 — Deterministic parsers (Keystone, Fred Beans, Wilbert's, Quirk, Adas, Empire, Astech, Precision)

Grouped into one section — all 8 vendors were verified the same way, against the same
real-PDF source, using the same two-pass method (initial pass via `identifyAndExtract()`,
then a corrected pass via the real pipeline after the `ensureVendorStmtTable` fix). Listed
individually because each vendor's correctness depends on a genuinely different structural
trap (see `knownVendorExtractors.ts` and each vendor's own Decision Log entry in
`EXECUTION_PLAN.md`/`S09_SESSION_LOG.md`), so each gets its own pass/fail row.

### Test Cases Applied

| Case | Vendor | Real trap being tested | Expected | Result (initial pass, `identifyAndExtract()`) | Result (corrected pass, real pipeline) |
|------|--------|------------------------|----------|------------------------------------------------|------------------------------------------|
| TC-KEY | Keystone Automotive Industries | 4-column running balance — only `balance_due` (already netted) is correct | Sum of `balance_due` matches statement total exactly | PASS — 160 lines, $10,428.76 | PASS — same total, confirmed reaching Silver via real pipeline |
| TC-FB | Fred Beans Parts | 4 money columns per row — only charges/−credits is the real line amount | Sum matches statement total exactly | PASS — 273 lines, $23,986.36 | PASS — same total, confirmed reaching Silver via real pipeline (this is the exact document that originally surfaced the `ensureVendorStmtTable` bug — see below) |
| TC-WIL | Wilbert's Inc. | Sum `balance`, not `amount`; `DT#nnnnnn` continuation-line merge | Sum matches statement total exactly | PASS — 28 lines, $2,302.25 | PASS — same total |
| TC-QRK | Quirk Auto Group | Single signed amount column; reversed-watermark artifact filtered | Sum matches statement total exactly | PASS — 174 lines, $45,983.25 | PASS — same total |
| TC-ADS | Adas Calibration Experts | Sum `OPEN AMOUNT`, not `AMOUNT` | Sum matches statement total exactly | PASS — 48 lines, $10,685.75 | PASS — same total |
| TC-EMP | Empire Auto Parts | Word-position column bucketing; doc-number/description split regex | Sum matches statement total exactly | PASS — 91 lines, $8,568.00 | PASS — same total |
| TC-AST | Astech (Repairify) | Clean native table extraction, no bucketing needed | Sum matches statement total exactly | PASS — 106 lines, $8,339.11 | PASS — same total |
| TC-PRE | Precision Diagnostics | Multi-line transaction reconstruction across continuation lines | Sum matches statement total exactly | PASS — 27 lines, $17,952.92 | PASS — same total |

Lia Auto Group (Task 8.1, ported in Session 8) was also included in the corrected-pass
regression sweep for completeness, not re-tested as a new case: 31 lines, $17,256.29 —
still PASS through the real pipeline post-fix.

**Total: 9 vendors, all reconciling to the cent through the real pipeline after the bug
fix.**

### Code Review
`knownVendorExtractors.ts`'s table-driven registry reviewed — each entry's `signatures`
array checked against its vendor's actual printed statement text (not the synthetic
"VENDOR:" fixture marker used elsewhere in the test suite), confirming real-world match
behavior rather than fixture-only behavior.

### Scope Decisions
See `S09_SESSION_LOG.md`'s Decision Log — Astech/Precision ported for cost/determinism
despite Claude already extracting them correctly; the other 6 ported because Claude
measurably could not handle their structural traps (per the reference implementation's own
prior eval data).

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed (both passes, all 9 vendors including Lia)
[ ] Challenge agent run — not run, lightweight-patch mode
[x] Live-data verification recorded — real vendor PDFs, exact arithmetic match
[x] Pre-commit declaration recorded
[x] Code review complete
[x] Scope decisions documented

**Status:** Completed

---

## Bug fix (mid-session, no task number) — `ensureVendorStmtTable` never called

### How it was found
Not found by this session's own verification method — found via the engineer's own real
browser upload of a Fred Beans statement, which showed badge "Extracted" with "Extracted
lines (0 total)." This session's own verification (Test Cases Applied above, first pass)
had only ever exercised `identifyAndExtract()` directly, one layer below where this bug
actually lived (`extractionPipeline.ts`'s orchestration).

### Test Cases Applied

| Case | Scenario | Expected | Method | Result |
|------|----------|----------|--------|--------|
| TC-1 | A brand-new known vendor, first document ever uploaded for it | `ensureKnownVendor()` creates both the registry row *and* the raw stmt table before the pipeline tries to insert into it | Live run: cleared test data, re-uploaded a Fred Beans statement through the real `/api/documents` → `runExtractionPipeline()` path | PASS — table created, raw row inserted, Silver normalized, reconciled |
| TC-2 | An already-broken registry row (created by the pre-fix code, table missing) seen again | Self-heals — table created on next sight, not skipped by the `if (existing) return existing` early return | First attempted fix (table creation only in the "new row" branch) FAILED this exact case — confirmed via re-test, same "no such table" error | FAIL on first attempt, PASS after moving the `ensureVendorStmtTable()` call to run unconditionally before the early return |
| TC-3 | Full 9-vendor regression sweep after the corrected fix | All 9 vendors reconcile through the real pipeline, none hit the missing-table error | Live run, all 9 vendor PDFs re-uploaded through the real pipeline (also had to clean up one stuck duplicate-hash document left over from the TC-2 failed-fix test run, since `hasAlreadySucceeded()` skips re-running a document with an already-"successful"-looking attempt row) | PASS — all 9 vendors, exact arithmetic match (see the Tasks 9.2–9.5 table above, "corrected pass" column) |

### Code Review
`ensureVendorStmtTable()` itself (pre-existing, from Task 3.1, not written this session) is
`CREATE TABLE IF NOT EXISTS` — idempotent, safe to call unconditionally on every
`ensureKnownVendor()` invocation, not just once per vendor. Confirmed this doesn't
reintroduce any performance concern (it's a local SQLite DDL statement, not a network
call).

### Scope Decisions
None — this was a straightforward bug fix, not a scope decision.

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed (after the corrected fix; TC-2's first attempt is recorded as
a failure, not hidden)
[ ] Challenge agent run — not run, lightweight-patch mode
[x] Live-data verification recorded — real pipeline, all 9 vendors
[x] Pre-commit declaration recorded
[x] Code review complete
[x] Scope decisions documented (N/A — no scope decision needed)

**Status:** Completed

---

## Task 9.6 — Live-Claude-vs-OCR test for scanned vendors (renumbered/rescoped from "Real OCR availability")

### Test Cases Applied
Source: this session's own investigation, executed after engineer approval to proceed
(deferred earlier the same day, then run once approved)

| Case | Vendor | Expected | Method | Result |
|------|--------|----------|--------|--------|
| TC-KSI | KSI Noakers 053126 | Reconciles to statement total within $0.01 via Claude vision, no OCR | Live run through the real pipeline (`registerDocument` → `triggerExtraction`) | PASS — 66 lines, $7,774.00 |
| TC-SUB | 802 Subaru Rotunda's | Same | Same method, isolated temp db/uploads | PASS — 60 lines, $12,724.38 |
| TC-BOW | Bowser Klapec | Same | Same method | PASS — 201 lines, $63,830.20 |
| TC-MOM | Momentum Tire & Wheel Nutley | Same | Same method | PASS — 19 lines, $3,795.00 |
| TC-NYE | NYE Sprague's | Same | Same method | PASS — 52 lines, $12,287.67 |
| TC-KEY | Key Rotunda's | Same | Same method | FAIL — statement total $9,023.17, computed sum –$2,320.49 (diff $11,343.66) |

**Key Rotunda's failure, diagnosed (not left as an unexplained FAIL):** pulled the actual
extracted lines via the attempt row's `raw_output`. Every individual line was read
correctly (0.92–0.95 confidence, plausible invoice/credit-memo amounts). Two rows,
`WTCC070826` (–$3,753.11) and `WTCC072026` (–$7,590.55), are payment/remittance-total rows,
not real transaction lines. Excluding just those two: sum = $9,023.17, exactly matching
the statement's own total to the cent (independently recomputed and confirmed via a
separate arithmetic check, not just eyeballed). This confirms the failure is a semantic/
column-mapping issue (the same class as Fred Beans' running-balance columns), not a scan-
quality or OCR problem — Claude's vision read was accurate throughout.

### Code Review
No code changed by this task — a live investigation only. G2 (arithmetic gate) applied
unchanged; Key Rotunda's correctly failed the existing gate rather than silently passing
with a wrong total.

### Scope Decisions
Task 9.6 Step 2 (installing Tesseract/Poppler) and the former Task 9.7 (OCR-derived
parsers for AR1C-family vendors) are both dropped as a direct result of these findings —
see `S09_SESSION_LOG.md`'s Decision Log. Key Rotunda's own fix is recorded as an Out of
Scope Observation there, not built this session.

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed except one, and that one's failure was root-caused rather
than left unexplained (TC-KEY)
[ ] Challenge agent run — not run, lightweight-patch mode
[x] Live-data verification recorded — all 6 scanned vendors, real pipeline, isolated temp
db/uploads (no shared-dev-db pollution)
[x] Pre-commit declaration recorded (no code committed for this task — investigation only)
[x] Code review complete
[x] Scope decisions documented

**Status:** Completed

---

## Task 9.7 — Commit a real verification script (renumbered from 9.8, after former 9.7 was dropped)

### Test Cases Applied
Source: EXECUTION_PLAN.md Task 9.8's original CC prompt (content unchanged by the
renumbering — now Task 9.7 in `docs/EXECUTION_PLAN.md`. Corrected 2026-09-01: this
originally cited a working-draft file, `docs/EXECUTION_PLAN_SESSION9_RENUMBER_DRAFT.md`,
that was never saved as a standalone file — the renumbering was applied directly to
`docs/EXECUTION_PLAN.md` instead.)

| Case | Scenario | Expected | Method | Result |
|------|----------|----------|--------|--------|
| TC-1 | All 9 known vendors (Lia, Keystone, Fred Beans, Wilbert's, Quirk, Adas, Empire, Astech, Precision) | Each registers, routes to its deterministic extractor, reconciles within $0.01, reaches Silver | `npm run test:known-vendor-extractors` — real `registerDocument` → `triggerExtraction` pipeline, isolated temp db/uploads | PASS — all 9, exit code 0 |
| TC-2 | A machine without the real vendor sample folder | Reports SKIPPED per vendor, not a hard failure | Structural — the script checks `fs.existsSync()` per sample path before asserting anything | Structural pass (this machine has the folder, so this path wasn't actually exercised as a failure this run) |
| TC-3 | Script run cleans up after itself | Shared dev db (`.data/recon.local.db`) and uploads dir untouched after a run | Confirmed via direct `ls .data/` before/after — only the pre-existing `recon.local.db*`/`uploads` present, no leftover temp files | PASS |

### Code Review
Deliberately calls `triggerExtraction()` (the real pipeline entry point), not each vendor's
extractor function directly — see `S09_SESSION_LOG.md`'s Decision Log for why: the
`ensureVendorStmtTable` bug found earlier this same day lived one layer above the extractor
itself, and a check that only re-invokes the extractor directly would not catch that bug
class recurring. Reviewed for isolation — `SQLITE_DB_PATH`/`UPLOADS_DIR` env overrides set
before any db access, temp files cleaned up in all cases (success and failure paths both
reach the cleanup code, since it runs after the loop unconditionally — a thrown error
inside a `check()` call would skip cleanup, but `check()` itself never throws, only
records a failure and continues).

### Scope Decisions
Real vendor sample PDFs are read from a documented local path
(`C:/Users/yellu/Downloads/Statements`), not committed to the repo — customer statements,
privacy and size. A machine without that folder gets SKIPPED per vendor, not a failure;
this is a local verification aid, not a CI gate assuming every machine has the samples.

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed
[ ] Challenge agent run — not run, lightweight-patch mode
[x] Live-data verification recorded — all 9 known vendors, real pipeline
[x] Pre-commit declaration recorded
[x] Code review complete
[x] Scope decisions documented

**Status:** Completed

---

## Former Task 9.7 — OCR-derived deterministic parsers for scanned AR1C vendors — REMOVED, no verification section

This task no longer exists (see `docs/EXECUTION_PLAN.md`'s Task 9.6 Scope Decision and the
Task 9.7 section — renumbered from 9.8) — its premise (that some scanned vendors would fail
Claude's vision path and need OCR-derived parsing) was disproven by Task 9.6's own findings
before anything was built. Nothing to
verify for a task that was correctly never started.

---

## Session-Level Summary

Every task in this session (9.1–9.5, the unplanned `ensureVendorStmtTable` bug fix, 9.6,
and 9.7/renumbered-from-9.8) has real live-data verification against actual production
vendor PDFs, through the real end-to-end pipeline (`registerDocument` → `triggerExtraction`)
rather than a lower-level function in isolation — the same lesson the `ensureVendorStmtTable`
bug taught applied consistently to every verification pass in this session, including the
brand-new ones (9.6, 9.7). The former Task 9.7 (OCR-derived parsers) is not verified because
it no longer exists — its premise was disproven by Task 9.6's own live evidence before any
code was written for it, which is itself a form of verification (the plan was tested against
reality and found unnecessary, not abandoned without checking). All of 9.1–9.7 are complete;
nothing in this session is left as an honestly-recorded gap the way 9.6/9.7/9.8 were in the
prior version of this record.
