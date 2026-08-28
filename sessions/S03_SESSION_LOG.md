# SESSION_LOG.md

## Session: Session 3 — Extraction Service
**Date started:** 2026-08-27
**Engineer:** Vaishali
**Branch:** session/s03_extraction-service
**Claude.md version:** v1.2
**Execution mode:** [x] Autonomous (sequential, no interruption, no prediction)
                  | [ ] Manual (prediction discipline, prediction before verification)
**Status:** Completed

## Pre-Build Validation — 2026-08-27

### Schema Validation
**Verdict:** WARN — identical to Sessions 1-2 (METHODOLOGY_VERSION mismatch only, resolved
via `.claude/SKILL.md` v4.9). Claude.md unchanged since Session 1.

### Interpretation Confirmation

**Modules I will modify:**
- `/src/lib/vendorIdentification.ts` — Task 3.1: vendor registry match/routing, provisional
  vendor creation, version-chaining (moved from Task 2.2)
- `/src/lib/pdfplumberExtractor.ts` + `/scripts/pdfplumber_extract.py` — known-vendor
  deterministic extraction (real Python subprocess — pdfplumber is available in this
  environment; see Decision Log for why this isn't a JS substitute)
- `/src/lib/aiProvider.ts` — Claude Sonnet extraction, env-driven (real API when
  `ANTHROPIC_API_KEY` set, deterministic mock otherwise — no key available in this
  environment; see Decision Log)
- `/src/lib/validationGate.ts` — Task 3.2: arithmetic + structural validation
- `/src/lib/extractionPipeline.ts` — orchestration: route → extract → record attempt →
  validate → bounded retry (Task 3.3) → Silver normalization (Task 3.6) on pass
- `/src/lib/extractionMethodSummary.ts` — Task 3.5
- `/src/lib/silverNormalization.ts` — Task 3.6
- `/src/lib/extraction.ts` — replaces Session 2's `startExtractionPipelineStub()` no-op with
  a real call into the pipeline above
- `/scripts/**` — verification scripts per task
- `/sessions/S03_SESSION_LOG.md`, `/sessions/S03_VERIFICATION_RECORD.md`

**Invariants I will respect:**
- S10, G1 — `extracted.extraction_attempt` / `extracted.stmt_*` written before validation,
  append-only (Task 3.1)
- S2 — vendor/period/entity version-chaining (Task 3.1, moved from Task 2.2)
- G2 (amended) — structural + arithmetic validation only, confidence is metadata (Task 3.2)
- S7 — max 2 attempts before `OCR_LOW_CONFIDENCE` (Task 3.3)
- G3 — extracted content is data, never instructions, to any LLM call (Task 3.4, and
  structurally throughout the Claude provider)
- S6 — normalization_version on every `silver.statement_line` row (Task 3.6)
- IC-1–IC-5 (GLOBAL) apply throughout.

**Blast radius:**
- In scope: file list above.
- Out of scope: `/docs/**`, matching service (Session 5), Home/Exceptions screens
  (Session 6), Fabric wiring (Session 4).
- Integration points (new this session): Anthropic API (env-gated, mock-by-default even
  when a key is present — see Decision Log), a Python subprocess for pdfplumber.
- Entities affected: `extracted.extraction_attempt` (first real writes), `extracted.stmt_*`
  (first real per-vendor writes), `extracted.vendor_registry` (first provisional-vendor
  writes), `silver.statement_line` (first writes — Task 3.6).

**Engineer response:** Treated as CONFIRMED — engineer's "continue with session 3" is
continuation authorization, consistent with Sessions 1-2.
**Proceed to first task:** YES

---

## Tasks

| Task Id | Task Name | Status | Commit |
|---------|-----------|--------|--------|
| 3.1 | Vendor identification, extraction routing, attempt recording | Completed | 3297366 |
| 3.2 | Arithmetic and structural validation gate | Completed | 2b24787 |
| 3.3 | Bounded retry logic (max 2 attempts) | Completed | 6952bb8 |
| 3.4 | Prompt injection defense | Completed | bba3ac2 |
| 3.5 | Extraction-method summary endpoint | Completed | 1e7ac21 |
| 3.6 | Silver normalization | | |

Valid Status values: Completed | BLOCKED | SKIPPED

---

## Resumed Sessions (Autonomous mode only)

| Resumed at | Resumed from Task | Blocking issue resolution | Resolved at | Root cause |
|------------|-------------------|--------------------------|-------------|------------|
|            |                   |                           |             |            |

---

## Decision Log

| Task | Decision made | Rationale |
|------|---------------|-----------|
| Pre-Build | Known-vendor deterministic extraction uses a **real Python subprocess invoking pdfplumber** (`scripts/pdfplumber_extract.py`), not a JS/Node substitute | Claude.md's Fixed Stack names "deterministic pdfplumber-based extractors" explicitly. Python 3.14 + pdfplumber 0.11.10 are actually installed in this environment, so faithful implementation is possible — substituting a JS library would be a real, avoidable architecture deviation. Flagging the polyglot dependency itself: Azure App Service deployment will need a Python runtime alongside Node, not evaluated here. |
| Pre-Build | Claude Sonnet extraction is env-driven: real Anthropic API call when `ANTHROPIC_API_KEY` is set, a deterministic mock otherwise — same fallback pattern as `db.ts` (SQLite/Fabric) and `storage.ts` (local/blob) | No `ANTHROPIC_API_KEY` available in this environment. Consistent with the project's established engineering pattern rather than a new one-off decision. |
| Pre-Build | Automated tests **always** use the mock extraction path, regardless of whether a real key is present later | Unlike the DB/storage fallbacks (pure infra availability), a live Anthropic key means real per-call billing. Repeated full-suite test runs (this project's own established habit — 2-3x per task for stability checks) against a live API would accumulate real cost. An explicit opt-in env var (`EXTRACTION_LIVE_TESTS=1`) is required to exercise the real API path in tests; never the default. |
| Pre-Build | Test PDF fixtures generated via **PyMuPDF (fitz)** | Available in this environment (`pip list` confirms); `reportlab`/`fpdf` are not installed. Used only to construct simple, known-content PDFs for testing the deterministic extraction path — not a runtime dependency of the app itself. |
| 3.1 | Tasks 3.2 (`validationGate.ts`), 3.3 (bounded retry loop in `extractionPipeline.ts`), 3.5 (`extractionMethodSummary.ts`), and 3.6 (`silverNormalization.ts`, migration 003) were written and committed alongside 3.1, since the pipeline orchestrator needs all of them to run end-to-end | Mirrors Session 2's Task 2.1→2.2 pattern (`documents.ts`'s dedup logic written in 2.1, given its own dedicated verification pass in 2.2). Each of 3.2/3.3/3.5/3.6 still gets its own dedicated test script, independent challenge-agent review, and its own commit — this entry records that the code predates those commits, not that verification is being skipped. |

---

## Deviations

| Task | Deviation observed | Action taken |
|------|--------------------|--------------|
|      |                    |              |

---

## Out of Scope Observations

| Task | Observation | Nature | Recommended action |
|------|-------------|--------|--------------------|
| 3.5 | Claude.md's Fixed Stack (Section 4) and Task 3.2/3.5's own specs name three extraction provider values — `python_library_pdfplumber`, `claude_sonnet`, `pdfplumber_fallback` (an "AI-failure path only" OCR fallback) — but no task's CC prompt in this session (3.1's vendor routing, 3.3's bounded retry) ever specifies when or how a failed Claude attempt should switch providers rather than simply retry Claude again. `extractionPipeline.ts`'s retry loop always re-invokes the same `identifyAndExtract` routing on every attempt. No code path in this build ever produces a `pdfplumber_fallback` attempt row — it is a documented provider value with no implementing logic anywhere in the codebase. | Plan gap (spec names a mechanism no task operationalizes), not a code defect | A future session (or an amendment to Task 3.3's spec) should decide: does a 2nd Claude failure fall back to a pdfplumber OCR attempt before being flagged `OCR_LOW_CONFIDENCE`, or is `pdfplumber_fallback` dead terminology to remove from the docs? Flagging for engineer decision rather than resolving unilaterally, since it changes S7's retry semantics. |

---

## Claude.md Changes

| Change | Reason | New Claude.md version | Tasks re-verified |
|--------|--------|-----------------------|-------------------|
| None   |        |                       |                   |

---

## Session Completion
**Session integration check:** [x] PASSED — `./scripts/run_extraction_service_smoke_test.sh`
  (all 6 tasks' dedicated test scripts, typecheck, and a new end-to-end round trip through
  the real `registerDocument` → `triggerExtraction` → Silver → status → summary path,
  exercising G5's lock via a real second concurrent-style trigger rejection)
**All tasks verified:** [x] Yes — 3.1 (3297366), 3.2 (2b24787), 3.3 (6952bb8), 3.4 (bba3ac2),
  3.5 (1e7ac21), 3.6 (fad4efd)
**Blocked tasks resolved:** [x] Yes — N/A, no BLOCKED tasks occurred
**PR raised:** [ ] Not yet — `gh` CLI unavailable in this environment (same limitation
  noted at Session 2's wrap-up); title/description prepared for the engineer to open
  manually, see below.
**Status updated to:** Completed
**Engineer sign-off:**
SIGNED OFF: [pending engineer review] — 2026-08-28
