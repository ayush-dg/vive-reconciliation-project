# SESSION_LOG.md

## Session: Session 9 — Per-Vendor Deterministic Parsers + Real OCR
**Date started:** 2026-09-01
**Engineer:** Vaishali
**Branch:** session/s06_home-exceptions-screens (continued)
**Claude.md version:** v1.3 (post-doc-sync)
**Execution mode:** [x] Lightweight scoped patch (same mode as Session 8 and the S06→S08
gap) — implement, verify against real data, brief self-review, commit. No scaffold, no
challenge-agent review, no Pre-Build Validation ceremony.
**Status:** Tasks 9.1–9.5 Completed. Task 9.6 (renumbered/rescoped 2026-09-01, see below)
Completed — live-tested the remaining scanned vendors against Claude directly; found OCR
unnecessary for 5 of 6, and the 6th's failure to be a semantic issue, not a scan-quality
one. The former Task 9.7 (OCR-derived parsers) is dropped as a direct result — its premise
didn't hold. Task 9.8 (commit a real verification script) is Completed and renumbered to
fill the vacated 9.7 slot.

## Note on process

Same lightweight-patch mode as Session 8 — this log is written honestly about that (no
Pre-Build Validation, no Challenge Agent review). Written retrospectively on engineer
request, same day as the work.

**Trigger:** analysis of a folder of 16 real vendor statement PDFs the engineer provided
(`C:\Users\yellu\Downloads\Statements`), requested specifically to answer "what's the fix"
for Fred Beans' post-Session-8 arithmetic-mismatch failure (a different, legitimate bug
from the crash Session 8 fixed — Fred Beans extracts real data now, but Claude conflates
four money columns per row into one, inflating the sum ~4.7x). Cross-referencing against
the reference implementation's own per-vendor parsers found: (a) 9 of 10 vendors already
have a proven, reusable deterministic extractor Session 8 didn't port; (b) 6 more vendors
in the same folder are scanned/image-only PDFs pdfplumber can't read at all, unrelated to
Session 8's fix.

---

## Tasks

| Task Id | Task Name | Status | Commit |
|---------|-----------|--------|--------|
| 9.1 | Extraction prompt: credit-sign + running-balance rules | Completed | 49614ab |
| 9.2 | Keystone Automotive Industries deterministic parser | Completed | 49614ab |
| 9.3 | Fred Beans Parts deterministic parser | Completed | 49614ab |
| 9.4 | Wilbert's, Quirk, Adas, Empire deterministic parsers | Completed | 1cf0581 |
| 9.5 | Astech, Precision deterministic parsers | Completed | 1cf0581 |
| — | **Bug fix (found + fixed mid-session, no task number):** `ensureKnownVendor()` never created the `extracted_stmt_<vendor_slug>` table it registered | Completed | b2a691c |
| 9.6 | Live-Claude-vs-OCR test for scanned vendors (renumbered/rescoped from "Real OCR availability") | Completed | — (live investigation, no code change) |
| 9.7 | Commit a real verification script (renumbered from 9.8, after 9.7/OCR-parsers was dropped) | Completed | — |
| — | *(former 9.7, "OCR-derived deterministic parsers for scanned AR1C vendors") — REMOVED 2026-09-01, premise didn't hold (see Decision Log)* | — | — |

Valid Status values: Completed | BLOCKED | SKIPPED | NOT STARTED

---

## Resumed Sessions (Autonomous mode only)

N/A — this session did not use Autonomous mode.

---

## Decision Log

| Task | Decision made | Rationale |
|------|---------------|-----------|
| 9.1 | Added two explicit prompt rules (credit-sign, running-balance-column) rather than trying to fix Fred Beans with a per-vendor prompt tweak | Matt Nimey Sprague's real statement showed the *identical* credit-sign bug independently of Fred Beans — a systemic prompt gap, not a one-vendor issue. Fixing it generically helps every vendor still on the Claude path, not just the one that happened to be reported. |
| 9.2/9.3/9.4/9.5 | Ported 8 more of the reference implementation's already-solved per-vendor parsers, rather than trying to prompt-engineer Claude into handling each vendor's specific column trap | The reference project's own eval data (found during this session's investigation) already measured this: their generic vendor-agnostic fallback scored 0% on Fred Beans and Keystone, 56–93% on the rest. A generic prompt — however well-tuned — was proven, by the reference project's own prior work, not to generalize across these specific structural traps (running balances, multi-column layouts, sign conventions). Porting proven logic was faster and more reliable than re-deriving it. |
| 9.2/9.3/9.4/9.5 | Refactored Task 8.1's single hardcoded Lia-only routing branch into `knownVendorExtractors.ts`, a table-driven registry, before adding more vendors | Adding 8 more vendors as 8 more copy-pasted `if` branches in `vendorIdentification.ts` would have made the routing function unreadable; a registry table (vendor slug + signatures + extractor fn) keeps adding a vendor to "one new file + one new entry," proven by doing it 8 times in a row without touching the core dispatch logic again after the refactor. |
| 9.4/9.5 | Ported Astech and Precision even though Claude's generic path already extracts them correctly | Cost (zero AI calls) and determinism, not correctness — explicitly recorded as a different rationale from 9.2/9.3/9.4's "Claude gets this wrong" cases, so a future reader doesn't mistake this for "Claude was also broken here." |
| (bug fix) | Fixed by calling the existing (previously unused) `ensureVendorStmtTable()` unconditionally inside `ensureKnownVendor()`, not just on the "insert a new registry row" branch | The bug was found live: a registry row already created by the pre-fix code path (during this session's own earlier browser testing) is exactly the broken state that needs repairing on next sight, not skipping. An early-return-on-existing-row version of the fix would have looked correct but silently failed to self-heal already-broken rows — confirmed by testing the naive version first and watching it fail identically. |
| 9.6 | Deferred within-session, then executed later the same day once the engineer approved proceeding | Mid-session, the engineer asked "what about base64 encoding" — surfacing that this app already sends every PDF to Claude as a base64 document block, meaning Claude can already read a scanned PDF via vision with no OCR at all. This reframed 9.6 entirely: installing Tesseract before even testing whether Claude's vision path already handles the 6 scanned vendors correctly would have been solving an unconfirmed problem. Revised plan: test live Claude against all 6 scanned PDFs first; only build OCR-based parsers for whichever fail the same structural way Fred Beans/Keystone did. |
| 9.6 | Live-tested all 5 remaining scanned vendors (KSI Noakers already tested separately) through the real `registerDocument → triggerExtraction` pipeline, isolated temp db/uploads, no shared-db pollution | Same lesson as the `ensureVendorStmtTable` bug — testing through the real entry point, not a lower-level function, is what actually proves the pipeline works end to end for these vendors, not just that Claude can read the text. |
| 9.6 | Result: 5 of 6 scanned vendors (KSI Noakers, 802 Subaru, Bowser Klapec, Momentum, NYE Sprague's) reconciled exactly via Claude vision, no OCR. Only Key Rotunda's failed ($9,023.17 vs. a computed –$2,320.49). Diagnosed the failure by inspecting its actual extracted lines rather than assuming OCR was the fix | Found Claude read every line correctly (0.92–0.95 confidence) but included two rows, `WTCC070826`/`WTCC072026`, that are payment/remittance-total rows, not real transactions — excluding just those two reconciles to the cent. This is a semantic/prompt-mapping issue, the same class of trap as Fred Beans' running-balance columns, not a scan-quality problem — meaning OCR would not have fixed it even if built. |
| 9.6/(former 9.7) | Dropped Task 9.6 Step 2 (installing Tesseract/Poppler) and the former Task 9.7 (OCR-derived parsers for AR1C-family vendors) entirely, rather than building either | Neither has a remaining reason to exist: no scanned vendor actually needs OCR to be read correctly (5/6 passed outright; the 6th's fix is a prompt-rule/small-parser problem, not an OCR one). Building OCR infrastructure for a problem that turned out not to exist would have been pure waste — confirmed by testing before building, exactly per this task's own revised plan. Key Rotunda's own fix is recorded as an Out of Scope Observation below, not silently dropped. |
| 9.7 (renumbered from 9.8) | Built `scripts/verify_known_vendor_extractors.mjs` against the real `registerDocument → triggerExtraction` pipeline, not each vendor's extractor function called directly, and running it in an isolated temp db/uploads dir rather than the shared dev db | The `ensureVendorStmtTable` bug (found earlier this same day) lived one layer above the extractor function itself — a verification script that only re-invokes the extractor directly would not have caught that bug class recurring in the future. Isolating the db/uploads avoids the exact "test data pollutes what the engineer sees in the browser" problem that came up repeatedly earlier in this session, without needing a manual cleanup cycle after every run. |

---

## Deviations

| Task | Deviation observed | Action taken |
|------|--------------------|---------------|
| All | No formal Challenge Agent review run, same as Session 8 | See `S09_VERIFICATION_RECORD.md`'s Verification Method note |
| 9.2–9.5 | **Real bug found via the engineer's own browser testing, not this session's own verification** — Fred Beans (and by extension every vendor from this session) showed "Extracted" badge with zero extracted lines after a real upload. Root cause: `extractionPipeline.ts`'s pre-existing raw-row write assumed a table `ensureKnownVendor()` never created. | Diagnosed via direct DB inspection (comparing a Claude-routed document's real silver lines against the deterministic-routed Fred Beans document's zero lines, then confirming the referenced table genuinely didn't exist). Fixed same-day; re-verified through the **actual full pipeline** (`registerDocument` → `runExtractionPipeline`), not just `identifyAndExtract()` in isolation — see the Out of Scope Observation below for why that distinction mattered. |
| (bug fix) | The first attempt at the fix (calling `ensureVendorStmtTable()` only inside the "no existing row" branch) still failed on re-test, because a broken registry row from *before* the fix already existed in the database from the engineer's own testing | Corrected to call `ensureVendorStmtTable()` unconditionally (it's `CREATE TABLE IF NOT EXISTS`, idempotent and cheap) — self-heals an already-broken row instead of only preventing new ones. Re-verified against all 9 vendors through the real pipeline after the correction. |

---

## Out of Scope Observations

| Task | Observation | Nature | Recommended action |
|------|-------------|--------|--------------------|
| 9.2–9.5 | Every one of this session's own verification scripts (before the bug was found) called `identifyAndExtract()` directly — one layer *below* where the `ensureVendorStmtTable` bug actually lives (`extractionPipeline.ts`'s orchestration, one level up). This is exactly why 8 vendors' worth of "verified" work shipped with a real bug undetected. | A genuine gap in this session's own testing methodology, not bad luck | Recorded here explicitly so it isn't repeated — the planned verification script (Task 9.8 at the time, renumbered to 9.7 later this same day) should exercise the real end-to-end pipeline, not just the extraction/routing layer, once it's built — and does, see Task 9.7 above |
| 9.6 | KSI Noakers was earlier suspected to be a hard, handwritten-annotation case (per visual inspection of a PNG render) — this turned out **wrong** once actually tested: it reconciled exactly via Claude vision, no issue at all | A prediction that didn't hold up against live testing | Recorded here as a reminder that visual suspicion isn't a substitute for actually testing — the same lesson as the `ensureVendorStmtTable` bug, in a different shape |
| 9.6 | Bowser Klapec is confirmed (via its own printed footer text) to be the same CDK "AR1C" statement software as Lia Auto Group and Key Rotunda's, just a scanned copy — yet it reconciled exactly via Claude vision with no issue, unlike Key Rotunda's | Real, useful finding — being the same underlying statement software doesn't predict which ones need special handling | Being "AR1C family" is not itself a reliable signal for which vendors need a dedicated parser; test each one directly rather than assuming from family membership |
| 9.6 | Key Rotunda's own fix (a prompt rule to recognize and exclude payment/remittance-total rows like `WTCC...`, or a small dedicated deterministic parser) is not built by this session | Engineer-directed scope stop (see Decision Log), not an oversight | One vendor's narrow, root-caused gap — pick up only if/when it's worth the engineering time; not a class of vendors needing OCR infrastructure |

---

## Claude.md Changes

| Change | Reason | New Claude.md version | Tasks re-verified |
|--------|--------|-----------------------|-------------------|
| None during the session itself | Lightweight-patch mode doesn't amend Claude.md in-session | — | — |

*(Claude.md v1.3 — see Session 8's log; the same doc-sync pass covered both sessions
together, after this session's own work completed.)*

---

## Session Completion
**Session integration check:** [x] PASSED — full Playwright suite (61 tests) run after
9.1–9.5 and after the bug fix (see Session 8's log for the 2 pre-existing, unrelated
flakes); `npx tsc --noEmit` and `npm run test:known-vendor-extractors` both clean after
Task 9.7 (renumbered from 9.8).
**All tasks verified:** [x] Yes — 9.1–9.5, the bug fix, 9.6 (live-tested, findings
recorded), and 9.7/renumbered-from-9.8 (script built, passing) all have real evidence
behind them..
**Blocked tasks resolved:** [x] Yes — N/A, no BLOCKED tasks occurred.
**PR raised:** [x] Yes
**Engineer sign-off:**  Vaishali — 2026-09-01
