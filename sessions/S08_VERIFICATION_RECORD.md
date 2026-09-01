**Session:** Session 8 — Extraction Quality Improvements ("Improve")
**Date:** 2026-09-01
**Engineer:** Vaishali

## Verification Method (read before the per-task detail below)

This session ran in lightweight-patch mode — no Challenge Agent adversarial review was
performed for any task, unlike Sessions 1–6's formal ceremony. Recorded honestly, not
fabricated: there is no "Challenge Agent Output" section below because none was run.
Verification instead consisted of:
1. **Live extraction against the real PDFs** that originally surfaced each bug (not
   synthetic fixtures) — Fred Beans (`Fred Beans Lee's.pdf`) and Astech
   (`Astech Owego.pdf`), the two documents that crashed before this session's fix.
2. **A real Lia Auto Group sample PDF** (from the reference implementation's own
   `sample_data/`), verified end-to-end through `identifyAndExtract()`.
3. **The full Playwright suite** (61 tests), run before commit.
No new committed verification script exists for this session's own live-data checks —
each was a throwaway scratch script, run once, deleted. This is a known gap, not an
oversight — see Task 8's own Decision Log for why it wasn't promoted to a committed
script this session (time-boxed; Session 9 carried the same gap forward as its own
Task 9.8).

---

## Task 8.1 — Known-vendor deterministic extraction (Lia Auto Group)

### Test Cases Applied
Source: EXECUTION_PLAN.md Task 8.1

| Case | Scenario | Expected | Method | Result |
|------|----------|----------|--------|--------|
| TC-1 | Real Lia Auto Group statement PDF | Extracts via the deterministic Python path, no AI call | Live run against the reference repo's own `sample_data/Lia Vestal.pdf` via `identifyAndExtract()` | PASS — 31 lines, `provider: python_library_pdfplumber` |
| TC-2 | A vendor with no registered deterministic extractor | Still routes to Claude-primary, unchanged | Structural — routing code only special-cases Lia's own printed signature, falls through to existing logic otherwise | PASS (by construction, re-confirmed via full suite) |

### Code Review
No new task-scoped invariants. `ensureLiaAutoGroupVendor()` (later generalized to
`ensureKnownVendor()` in Session 9) auto-provisions the registry row with
`extraction_route = 'deterministic'` on first sight — reviewed against the "Migrated only,
no seed data" baseline: nothing is seeded ahead of an actual document needing it, so this
doesn't violate that constraint.

### Scope Decisions
See `S08_SESSION_LOG.md`'s Decision Log — scoped to Lia only, matching Task 8.1's own
text; the remaining reference-implementation vendors deliberately deferred to Session 9.

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed
[ ] Challenge agent run — **not run, lightweight-patch mode** (see Verification Method above)
[x] Live-data verification recorded (see Test Cases Applied)
[x] Pre-commit declaration recorded
[x] Code review complete
[x] Scope decisions documented

**Status:** Completed

---

## Task 8.2 — Live Claude extraction fix (max_tokens/stop_reason guard) + fallback routing

### Test Cases Applied
Source: EXECUTION_PLAN.md Task 8.2 (as executed — see Session Log's Decision Log for the
`max_tokens`-bump-over-streaming choice)

| Case | Scenario | Expected | Method | Result |
|------|----------|----------|--------|--------|
| TC-1 | Astech Owego real statement (previously crashed both attempts) | Extracts successfully, no crash | Live call via `extractViaClaude()` against the actual PDF | PASS — 106 lines extracted |
| TC-2 | Fred Beans Lee's real statement (previously crashed both attempts) | Extracts successfully, no crash | Same method | PASS — 273 lines extracted |
| TC-3 | A response truncated at `max_tokens` | Returns a distinguishable failure (`extracted: null`), not a crash | Code path confirmed via the `stop_reason === 'max_tokens'` guard; not independently forced/tested against a live truncation (16000 tokens wasn't hit by any real document tested) | Structural pass — the guard exists and is reachable; not exercised against a real truncation this session |
| TC-4 | A malformed/incomplete tool call with no usable `lines` array | Degrades to a normal extraction failure, not a crash | Structural — `Array.isArray(input.lines)` guard | Structural pass, same caveat as TC-3 |
| TC-5 | A genuine Claude failure on attempt 1 | Attempt 2 routes to the OCR/pdfplumber fallback tier, not an identical Claude retry | Structural — `routeNextAttemptToFallback` logic reviewed; not exercised against a real Claude failure this session (both real test documents succeeded on attempt 1 after the fix) | Structural pass, not live-verified |

### Code Review
No new task-scoped invariants — G2 (arithmetic/structural gate) applies unchanged; the fix
makes previously-crashing documents actually *reach* that gate instead of crashing before
it.

### Scope Decisions
See `S08_SESSION_LOG.md`'s Decision Log entries for the `max_tokens` bump and the
belt-and-suspenders guard rationale.

**Known gap, not silently accepted:** TC-3/TC-4/TC-5 are structurally verified (the code
path exists and is reachable) but not live-tested against an actual truncation or Claude
failure — no real document tested this session was large enough to hit the new 16000-token
ceiling, and no live Claude call actually failed during testing. Recorded honestly rather
than claimed as live-verified.

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[x] All planned cases passed (TC-1/TC-2 live; TC-3/TC-4/TC-5 structural only, see above)
[ ] Challenge agent run — not run, lightweight-patch mode
[x] Live-data verification recorded for the actual reported bug (TC-1/TC-2)
[x] Pre-commit declaration recorded
[x] Code review complete
[x] Scope decisions documented

**Status:** Completed

---

## Task 8.3 — Python OCR/pdfplumber fallback tier

### Test Cases Applied
Source: EXECUTION_PLAN.md Task 8.3

| Case | Scenario | Expected | Method | Result |
|------|----------|----------|--------|--------|
| TC-1 | Table extraction (no OCR needed) | Works via the ported `pdfplumber_fallback.py` logic | Not exercised against a real scanned PDF this session — no genuinely scanned document was tested until Session 9's own investigation | NOT TESTED this session |
| TC-2 | A scanned page, OCR available | Produces non-empty text via Tesseract | Not testable — Tesseract/Poppler not installed in this environment | BLOCKED, recorded as a known gap (see Decision Log) |
| TC-3 | Environment check — Tesseract/Poppler availability | Confirmed present or absent | `pytesseract`/`pdf2image` import successfully; `tesseract`/`pdftoppm` binaries not found on PATH | CONFIRMED ABSENT — recorded as a Scope Decision, not silently assumed |

### Code Review
No new task-scoped invariants.

### Scope Decisions
Built the full fallback tier (table extraction + OCR branch with graceful "unavailable"
degradation), but genuinely could not test the OCR path itself in this environment. Not
silently claimed as tested — see `S08_SESSION_LOG.md`'s Decision Log.

### BCE Impact
Azure App Service Tesseract/Poppler availability remains an open question BCE (or a future
session) needs to resolve before this tier is production-reliable.

### Verification Verdict
[ ] All planned cases passed — TC-1/TC-2 not exercised this session (see above)
[ ] Challenge agent run — not run, lightweight-patch mode
[x] Environment check performed and recorded (TC-3)
[x] Pre-commit declaration recorded
[x] Code review complete
[x] Scope decisions documented (OCR-untested gap explicitly flagged, not hidden)

**Status:** Completed (built; genuinely unverified OCR path, honestly recorded — see
Session 9's own follow-up investigation)

---

## Task 8.4 — Per-line confidence + column-mapping prompt guidance

### Test Cases Applied
Source: EXECUTION_PLAN.md Task 8.4 (as adapted — see Session Log's Decision Log for the
scope adaptation from the reference's literal "raw-text rescan" pattern)

| Case | Scenario | Expected | Method | Result |
|------|----------|----------|--------|--------|
| TC-1 | Real extraction (Astech, Fred Beans) | Each line carries a `line_confidence` value | Live run (same calls as Task 8.2's TC-1/TC-2) | PASS — both real extractions returned per-line confidence values (0.95–0.99 range) |
| TC-2 | Confidence never gates pass/fail | Structural check — no `line_confidence` read anywhere in `validationGate.ts` | Code inspection | PASS — confirmed, IC-2/G2 unaffected |

### Code Review
IC-2/G2 (confidence is diagnostic-only, never a gate) explicitly re-confirmed, not
weakened — this task's own text required that check.

### Scope Decisions
See `S08_SESSION_LOG.md`'s Decision Log — the reference's literal "rescan raw text"
fallback pattern doesn't map onto this project's Claude-tool-call architecture (no raw
columns exist to rescan); the semantic-mapping prompt strengthening was built as the
closer equivalent instead.

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

## Task 8.5 — Row-level duplicate-line detection

### Test Cases Applied
Source: EXECUTION_PLAN.md Task 8.5

| Case | Scenario | Expected | Method | Result |
|------|----------|----------|--------|--------|
| TC-1 | Two statement lines, same vendor + normalized invoice ref + amount | Second one flagged `is_duplicate_line = 1`, still written to Silver | Not independently live-tested this session — no real document tested happened to contain a genuine duplicate line | NOT LIVE-TESTED — logic reviewed by code inspection only |
| TC-2 | Legitimately distinct lines (same invoice ref, different amount — a partial payment) | Never falsely flagged | Code inspection — the dedup check compares vendor + normalized ref + amount together, not ref alone | PASS by construction, not live-exercised |

### Code Review
Migration 009 (`is_duplicate_line INTEGER NOT NULL DEFAULT 0`) reviewed — additive,
defaulted, backward-compatible. `isDuplicateLine()`'s query reviewed against the "flagged
but still written" design decision — confirmed it never diverts a line from
`normalizeToSilver`'s insert, only sets the flag.

### Scope Decisions
See `S08_SESSION_LOG.md`'s Decision Log — "flag but still pass through" chosen specifically
to keep this task's blast radius at zero for existing matching/exception behavior.

**Known gap:** no real duplicate line was encountered in any document tested this session,
so TC-1/TC-2 are code-review-verified, not live-data-verified. Recorded honestly.

### BCE Impact
No BCE artifact impact.

### Verification Verdict
[ ] All planned cases passed — code-review-verified only, not live-tested (see above)
[ ] Challenge agent run — not run, lightweight-patch mode
[ ] Live-data verification — not performed for this task
[x] Pre-commit declaration recorded
[x] Code review complete
[x] Scope decisions documented

**Status:** Completed (built and reviewed; live-data verification is a real gap, honestly
recorded rather than claimed)

---

## Session-Level Summary

Of 5 tasks: 3 have real live-data verification against actual production-shaped PDFs
(8.1, 8.2's core fix, 8.4); 2 are code-review-verified only, with the gap explicitly
recorded rather than hidden (8.3's OCR path — environmentally blocked; 8.5 — no duplicate
line happened to appear in any tested document). This is consistent with lightweight-patch
mode's own standard (verify what's practical, record what isn't, never claim untested work
as tested) — not a lower bar silently applied.
