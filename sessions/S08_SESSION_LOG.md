# SESSION_LOG.md

## Session: Session 8 — Extraction Quality Improvements ("Improve")
**Date started:** 2026-09-01
**Engineer:** Vaishali
**Branch:** session/s06_home-exceptions-screens (continued)
**Claude.md version:** v1.2 (at session start — bumped to v1.3 in the post-session doc-sync)
**Execution mode:** [ ] Autonomous (sequential, no interruption, no prediction)
                  | [x] Lightweight scoped patch (engineer-confirmed, this and every
                  session since Session 6's completion) — implement, verify against real
                  data, brief self-review, commit. No scaffold, no challenge-agent review,
                  no Pre-Build Validation ceremony.
**Status:** Completed (Tasks 8.1–8.5); no BLOCKED tasks

## Note on process

This session ran in the lightweight-patch mode the engineer confirmed at the start of the
Session 6→8 gap, not Sessions 1–6's full PBVI ceremony. This log is written honestly
about that: there is no Pre-Build Validation section (none was performed), and the
Verification Record's "verification method" is live-data reconciliation testing plus the
full Playwright suite, not a Challenge Agent adversarial review (none was run). Written
retrospectively, same day, on engineer request — not reconstructed ceremony.

**Trigger:** the engineer reported Fred Beans and Astech statements failing extraction.
Diagnosis (via `aiProvider.ts` inspection + a live scratch-script call against the actual
PDFs) found a real crash: `input.lines.map()` on `undefined` when Claude's tool-call
response was truncated by `max_tokens: 4096` before finishing a large statement's `lines`
array — confirmed live against Fred Beans (273 lines needed) and Astech (106 lines). This
became Task 8.2. Tasks 8.1/8.3/8.4/8.5 were already planned in EXECUTION_PLAN.md
(added 2026-08-28, never executed) and were pulled forward as directly relevant follow-on
work once 8.2's root cause was understood.

---

## Tasks

| Task Id | Task Name | Status | Commit |
|---------|-----------|--------|--------|
| 8.1 | Known-vendor deterministic extraction — Lia Auto Group | Completed | 86af486 |
| 8.2 | Live Claude extraction fix (max_tokens/stop_reason guard) + fallback routing | Completed | 86af486 |
| 8.3 | Python OCR/pdfplumber fallback tier | Completed (built; OCR itself inert pending Tesseract/Poppler) | 86af486 |
| 8.4 | Per-line confidence + column-mapping prompt guidance | Completed | 86af486 |
| 8.5 | Row-level duplicate-line detection | Completed | 86af486 |

Valid Status values: Completed | BLOCKED | SKIPPED

All five tasks landed in a single commit (`86af486`) — lightweight-patch mode does not
enforce Sessions 1–6's one-commit-per-task discipline; verified together as one coherent
unit before committing (see Verification Record).

---

## Resumed Sessions (Autonomous mode only)

N/A — this session did not use Autonomous mode.

---

## Decision Log

| Task | Decision made | Rationale |
|------|---------------|-----------|
| 8.2 | Raised `max_tokens` 4096→16000 rather than switching to streaming | The `claude-api` skill's own guidance names 16000 as the safe non-streaming default (SDK HTTP timeouts are the actual risk streaming avoids); 16000 is comfortably above every real statement seen so far, and streaming would have been a materially larger code-shape change for a narrowly-scoped fix. Verified live against the two documents that actually crashed (see Verification Record). |
| 8.2 | Added an explicit `stop_reason === 'max_tokens'` guard *and* a defensive `Array.isArray(input.lines)` check, not just the `max_tokens` bump | The bump fixes today's known cases; a future statement large enough to exceed even 16000 tokens should fail with a clear, attempt-recorded reason, not repeat today's uncaught crash. Belt-and-suspenders, not redundant — the second guard covers a genuinely different failure shape (a malformed/incomplete tool call that isn't specifically a `max_tokens` stop). |
| 8.2 | Retry-to-fallback routing only fires when `provider === 'claude_sonnet' && extracted === null` (a genuine Claude failure), never for a validation-only failure (`extracted !== null` but arithmetic/structural failed) | Preserves existing retry behavior for the common case (retry the same path) unchanged; only routes to the new fallback tier for the specific failure class Task 8.2 exists to recover from. |
| 8.1 | Ported only Lia Auto Group (of the reference implementation's ~10 known vendors), matching Task 8.1's own scoped text | The reference repo's `adapter.py` covers many more vendors, but Task 8.1's CC prompt names Lia specifically ("a real Lia Auto Group statement is already available as a test case") — the rest were deliberately left for Session 9 rather than scope-creeping this session. |
| 8.3 | Built the OCR/pdfplumber fallback tier fully, but did not install Tesseract/Poppler | Confirmed live: the Python packages (`pytesseract`, `pdf2image`) are present in this environment, but the system binaries are not — installing new system software is a different kind of change than code, and per the task's own text ("confirm Tesseract is installable... flag as a Scope Decision if it isn't"), this is flagged rather than silently done. The fallback tier degrades gracefully (table-extraction-only, OCR branch reports "unavailable") rather than being blocked on the install. |
| 8.4 | Added per-line `line_confidence` to Claude's tool schema, but did not implement a literal "scan raw text for a plausible candidate" fallback as the reference's own Task 8.4 CC prompt describes | That fallback pattern belongs to the reference project's *different* architecture (Python-side table/OCR parsing with literal raw-text columns to re-scan) — this project's Claude call already returns structured JSON directly via a forced tool call, with no raw "columns" for a post-hoc TS-side scan to operate on. The closer equivalent — strengthening the prompt's semantic column-mapping guidance — was built instead; recorded as a deliberate scope adaptation, not an omission. |
| 8.5 | Row-level duplicate lines are flagged (`is_duplicate_line`) but still written to Silver and still reach matching unchanged | The task's own text left this as an open engineer decision ("flagged but still reaches Silver" vs. "diverted before Silver"). Chosen to keep this task's blast radius at zero for existing reconciliation behavior — a duplicate is a new *signal*, not a behavior change to what matching/exceptions ever see. |

---

## Deviations

| Task | Deviation observed | Action taken |
|------|--------------------|---------------|
| All | No formal Challenge Agent review was run for any task in this session (lightweight-patch mode, engineer-confirmed) | Verification instead consisted of: (1) live extraction against the actual real PDFs that originally crashed, confirming the fix; (2) a full Playwright suite run before commit. See `S08_VERIFICATION_RECORD.md`'s "Verification Method" note. Not silently substituted — recorded here explicitly. |
| 8.3 | OCR is built but genuinely non-functional in this environment (Tesseract/Poppler not installed) | Not fixed this session — see Decision Log. A real Scope Decision, not a bug: the fallback tier degrades to table-extraction-only rather than erroring. |

---

## Out of Scope Observations

| Task | Observation | Nature | Recommended action |
|------|-------------|--------|--------------------|
| 8.1/8.3 | Task 8.1's own CC prompt names 9 more vendors the reference implementation already has parsers for (Fred Beans, Keystone, Wilbert's, Quirk, Adas, Empire, Astech, Precision — plus KSI which the reference project itself never wired to production). None were ported this session. | Scoping gap, not a defect | Became Session 9's own scope, not silently dropped |
| 8.3 | Tesseract/Poppler availability on the actual Azure App Service deployment target (as opposed to this local dev machine) was never checked | Genuinely unresolved | Flagged again in Session 9's own Task 9.6 note — needs a real answer before OCR can be relied on in production |

---

## Claude.md Changes

| Change | Reason | New Claude.md version | Tasks re-verified |
|--------|--------|-----------------------|-------------------|
| None during the session itself | Lightweight-patch mode doesn't amend Claude.md in-session, per Section 3's own rule | — | — |

*(Claude.md was amended to v1.3 in the post-session doc-sync pass — see docs/Claude.md's
own v1.3 changelog entry — but that happened after this session's own work, covering both
Session 8 and 9 together, not as part of Session 8 itself. Corrected 2026-09-01: this note
originally cited a working-draft file, `docs/DOC_SYNC_DRAFT_AMENDMENTS.md`, that was never
saved as a standalone file — its content was applied directly to docs/Claude.md instead.)*

---

## Session Completion
**Session integration check:** [x] PASSED — full Playwright suite (61 tests) run before
commit; 2 known pre-existing flakes unrelated to this session's changes (a test-data
amount-collision in an unrelated CCC-corroboration test, and a stale document from an
earlier manual test run stuck mid-`processing` in the shared persistent local db — both
confirmed via direct DB inspection, not live bugs).
**All tasks verified:** [x] Yes — 8.1–8.5, all commit `86af486`. See
`S08_VERIFICATION_RECORD.md` for the live-data reconciliation evidence per task.
**Blocked tasks resolved:** [x] Yes — N/A, no BLOCKED tasks occurred.
**PR raised:** [x] Yes
**Status updated to:** Completed
**Engineer sign-off:** Vaishali — 2026-09-01
