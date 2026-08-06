# INVARIANTS.md — VIVE Reconciliation
Updated: 2026-08-05

## Changelog
| Version | Date | Author | Change |
|---|---|---|---|
| v1.0 | 2026-07-24 | CD | Initial draft, 5 GLOBAL invariants |
| v1.1 | 2026-07-24 | Ayush Kumar Sinha | INV-05 narrowed to per-filename (not system-wide) to enable parallel worker pool |
| v1.2 | 2026-07-27 | Ayush Kumar Sinha | Updated enforcement status for all invariants to reflect current build state |
| v1.3 | 2026-08-05 | Ayush Kumar Sinha (verified via Claude Code, direct code + git trace) | **Full verification pass on INV-04, INV-05, INV-06, and Engineer Sign-Off.** All claims PASS against live code and git history — no corrections needed this round. Evidence and two standing caveats added inline: (1) INV-04's two-layer gate is enforced entirely in application code, not backed by a database constraint. (2) INV-06's stale-lock failure mode is confirmed genuinely unmitigated — no signal handler or kill-cleanup exists. |
| v1.4 | 2026-08-05 | Ayush Kumar Sinha | **INV-01 amended: confidence threshold raised from 0.60 to 0.90.** Recorded honestly as an engineer judgment call, not a data-validated decision — a calibration check found 82% of the live database's confidence values were a stale pre-fix constant, the 0.80–0.89 band was empty, and only 2 human dispositions existed in total (too few to judge accuracy at any band). See INV-01 for full basis. This change must be propagated to every file in the repo that references the `0.60` threshold — config, code, tests, and docs — to avoid contradictory values. Implementation tracked separately from this document. |
| v1.5 | 2026-08-05 | Ayush Kumar Sinha (verified via Claude Code) | **Implementation of v1.4 completed and verified.** 0.90 propagated repo-wide via full audit (11 confirmed locations updated, historical/unrelated items correctly left untouched). Full test suite re-run: 281 passed / 18 failed, identical to pre-change baseline — no regression. **New consequence documented in INV-01:** pdfplumber-fallback row confidence values (0.65/0.50) were deliberately left unchanged, so all fallback rows — OCR or not — now route to review, a real behavior change worth monitoring in production. |
| v1.6 | 2026-08-06 | Ayush Kumar Sinha (verified via Claude Code) | **INV-06 reclassified from GLOBAL to TASK-SCOPED.** Triggered by a teammate doc-review flag noting this document's "Scope: GLOBAL" on INV-06 contradicted `docs/Claude.md` Section 2's own cross-reference footnote ("not a sixth GLOBAL invariant"). Verified against `dg-os/skills/PBVI/pbvi_core.md`'s Claude.md Schema (Section 2 must contain *every* GLOBAL invariant from this document, capped at five total — no mechanism exists for a GLOBAL invariant to be excluded from Claude.md) and `pbvi_brownfield.md`'s five-GLOBAL ceiling ("the engineer cannot sign off INVARIANTS.md with more than five GLOBAL invariants"). This document already had five other GLOBAL invariants (INV-01–05); INV-06 as a sixth was the actual source of the contradiction, not Claude.md's footnote. This reclassification brings this document in line with `discovery/INVARIANT_CATALOGUE.md`'s IC-06, which had already independently resolved the identical ambiguity as TASK-SCOPED. Claude.md's now-unnecessary footnote is removed in the same pass — see Claude.md changelog. |

---

## INV-01 — Confidence-gated human review

**Scope:** GLOBAL

**Amended 2026-08-05:** Threshold raised from `0.60` to `0.90`. Any row whose extraction confidence falls below the configured threshold (`0.90`) must be routed to human review — never silently pass into Bronze/Silver as if it were a fully-trusted extraction. Rows that fail this gate are written to `validation_document_review_queue` with `rejection_category = MISSING_MANDATORY_FIELD` or handled via the row-skip path depending on failure mode.

**Basis for this amendment — recorded honestly:** this was an **engineer judgment call, not a data-validated decision**. A calibration check was run against the live dev/test database (2026-08-05, Claude Code, direct query) before the change:
- 82% of rows in that database (2,046 of 2,483) carried a stale, hardcoded `0.75` confidence value from before Claude Sonnet's 2026-07-24 fix — not real signal, and excluded from any conclusion.
- The 0.80–0.89 band was completely empty in that data, before and after the fix — no row has ever landed there.
- Of the 278 genuinely post-fix Claude Sonnet rows, **zero scored below 0.91** — real extractions are already clustering at 0.91+.
- Only **2 human dispositions exist in the entire database**, both `ACCEPTED`, both already in the 0.90–0.94 band. **Zero `DISPUTED` records exist at any confidence level.** This is not enough data to support or contradict a threshold change on accuracy grounds — the sample is too small to draw either conclusion.
- **Do not cite this amendment as data-backed.** If asked why 0.90, the honest answer is: real post-fix extractions already cluster above 0.91 in the available sample, and this is a conservative engineering choice made ahead of having enough production disposition data to calibrate the threshold empirically. Re-run the same calibration check once a real production month of disposition data exists, and revisit this number then.

**Current enforcement status:** PARTIAL. The mechanical check always runs (`notebooks/01_document_intake.py:validate_invoice()`). Claude Sonnet 4.6 (active primary) was fixed 2026-07-24 — it now returns a genuine per-row confidence value instead of the old hardcoded `0.75` constant. `GeminiClient` and `MistralClient` remain broken but dormant, still hardcoding `0.75`. `match_confidence` (a separate field on `gold_matched_invoices` and `gold_exceptions`) is now genuine, but that is a different signal from extraction confidence.

**Verified 2026-08-05 (Claude Code, direct trace):** prior to this amendment, `config/validation/extraction_rules.json` confirmed `"confidence_threshold": 0.60`; `notebooks/01_document_intake.py:125-127` applies whatever value is configured and routes failing rows away from `valid_invoices` before `write_to_bronze()` is ever called. **This code path itself does not need to change — only the configured value does.**

**Implementation completed 2026-08-05 (Claude Code):** the 0.90 value was propagated across the full repo — `config/validation/extraction_rules.json`, `notebooks/01_document_intake.py`, `docs/ARCHITECTURE.md`, `RULES.md`, `src/ai/claude_sonnet_client.py`, and test fixtures in `tests/test_document_understanding_engine.py`. Historical/changelog entries and unrelated fields (e.g. the matching engine's separate `match_confidence` scoring, `document_type_confidence`) were deliberately left untouched. Full test suite re-run after the change: **281 passed, 18 failed — identical failing tests to the pre-change baseline**, confirming no regression from the threshold change itself (the 18 failures are pre-existing local-environment issues: 17 Azure CLI auth blocked on this machine, 1 known Windows tempfile lock).

**Real consequence surfaced by implementation, deliberately not papered over:** `src/ai/pdfplumber_fallback.py`'s row-confidence values (`0.65` for native/non-OCR rows, `0.50` for OCR-derived rows) were **not** raised alongside the gate — raising them to compensate would have been a second, undiscussed design decision riding on this one. Consequence: both values now sit below the 0.90 gate, so **all pdfplumber-fallback rows — OCR-derived or not — now route to human review**, not just the OCR ones as before. This is a genuine behavior change worth monitoring once real production volume exists (pdfplumber fallback only fires when all AI providers fail, so the practical impact depends on how often that happens) — documented here rather than silently left inconsistent with the code.

**This is never negotiable.**

---

## INV-02 — Matching is 100% deterministic, zero AI involvement

**Scope:** GLOBAL

The matching engine makes every match/exception decision through deterministic rules only — no AI model is ever consulted inside the matching step, for any reason. `match_confidence` scoring is computed by deterministic rule (match type), not by an AI model.

**Current enforcement status:** YES — confirmed. No import of, or call into, any AI client anywhere in the matching module.

**Verified 2026-08-05 (Claude Code, direct trace):** `src/matching/engine.py`'s full import list is `json, os, sys, uuid, hashlib, datetime, src.lakehouse.connection, src.shop_owners` — zero AI/LLM imports. `score_match_confidence()` is a pure dictionary lookup keyed by match type, no network or model call.

**This is never negotiable.**

---

## INV-03 — No totals/summary row may be ingested as an invoice line

**Scope:** GLOBAL

A vendor statement's grand-total, subtotal, or balance-forward row must never be extracted and validated as if it were a real invoice line.

**Current enforcement status:** PARTIAL — enforced in `pdfplumber_fallback.py` and `claude_sonnet_client.py` (active primary). Still absent in `GeminiClient`/`MistralClient` (both dormant, not a live risk).

**This is never negotiable.**

---

## INV-04 — `invoice_number` and `outstanding_amount` must never be null in Silver

**Scope:** GLOBAL

Every row written to the Silver layer must carry both an invoice identifier and an amount. Rows missing either field are skipped before reaching Silver and written to `gold_exceptions` as `EXTRACTION_INCOMPLETE`, or to `validation_document_review_queue` as `MISSING_MANDATORY_FIELD`.

**Current enforcement status:** YES — enforced by a two-layer gate (`get_skip_reason()` broad skip + `validate_invoice()` required_fields check).

**Verified 2026-08-05 (Claude Code, direct trace):** confirmed as two genuinely distinct functions, run in sequence — `get_skip_reason()` (`01_document_intake.py:195-214`, the broad net: no identifier *and* no amount at all → outright skip) runs first, then `validate_invoice()` (`01_document_intake.py:96-129`, specifically the `required_fields` check at 106-110) catches a row missing just one of the two fields. Both are pure Python checks that run before `write_to_bronze()`.

**Caveat — application-level only, no database backstop:** `migrations/001_initial_schema.sql:61,69` declares `invoice_number TEXT` and `outstanding_amount REAL` **without `NOT NULL`**. Neither enforcement function touches the database. A write path that bypassed this code (e.g. a direct SQL insert) would not be blocked by the schema itself — the invariant currently depends entirely on every write going through `01_document_intake.py`.

**This is never negotiable.**

---

## INV-05 — At most one job per `pdf_filename` may be in PROCESSING status at a time

**Scope:** GLOBAL

**Amended 2026-07-24:** Original wording was "at most one job PROCESSING system-wide." Narrowed by direct engineer instruction to enable the parallel worker pool. Two jobs for the SAME PDF must never be claimed and processed concurrently (they race the same `extraction_cache` row). Different filenames MAY process concurrently, up to `WORKER_POOL_SIZE` (default 3).

**Current enforcement status:** YES — enforced by atomic `UPDATE ... WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE status = 'PROCESSING' AND pdf_filename = ?)` guard in `web/queries.py:claim_next_pending_job()`. Race condition fix committed as `dc7e64a`.

**Verified 2026-08-05 (Claude Code, direct trace):** commit `dc7e64a` ("Fix web upload cache miss — same PDF uploaded twice should cache hit") confirmed in `git log`. Its diff replaces a plain `SELECT ... LIMIT 1` (`get_next_pending_job()`) with a single atomic `UPDATE jobs SET status = 'PROCESSING' ... WHERE id = (SELECT MIN(id) FROM jobs WHERE status = 'PENDING') AND status = 'PENDING' AND NOT EXISTS (SELECT 1 FROM jobs WHERE status = 'PROCESSING')` — exactly the claimed pattern. Note: that specific commit's guard was system-wide `PROCESSING`; the current per-`pdf_filename` scoping shown in this doc's enforcement line comes from a subsequent commit, consistent with the documented 2026-07-24 amendment above. The introduction of the atomic-claim pattern in `dc7e64a` checks out; the commit title ("cache miss" symptom) matches its body and diff (root cause: job-claiming race).

**This is never negotiable for the per-filename statement. Do not revert to the system-wide statement without an explicit engineer decision.**

---

## INV-06 — No more than `VIVE_MAX_CONCURRENT_AI_CALLS` Claude Sonnet extraction calls may run concurrently system-wide

**Scope:** TASK-SCOPED — tasks touching `src/ai/` (extraction clients, concurrency limiter) or `web/worker.py`

**Reclassified 2026-08-06 (from GLOBAL):** previously marked GLOBAL, which put this document at six GLOBAL invariants — over `pbvi_core.md`'s hard five-GLOBAL ceiling — and was the actual source of the contradiction with `docs/Claude.md` Section 2's cross-reference footnote ("not a sixth GLOBAL invariant"), rather than the footnote being wrong. `discovery/INVARIANT_CATALOGUE.md`'s IC-06 (the BCE counterpart of this same invariant) had already independently resolved this exact ambiguity as TASK-SCOPED, applying the test: no task touching, e.g., the users or batches router has any plausible interaction with AI-call concurrency — only tasks touching the extraction/worker layer do. This reclassification brings this document in line with IC-06 instead of contradicting it.

**Source:** Code-observed only — added 2026-07-25, following the worker-pool change that made this cap necessary.

**Enforcement point:** `src/ai/concurrency_limiter.py:ai_call_slot()` — a cross-process file-lock semaphore (`lakehouse/ai_call_slots/slot_0.lock` … `slot_{N-1}.lock`, exclusive-create via `os.O_CREAT | os.O_EXCL`, atomic on both POSIX and Windows). Wraps only the real network call in `src/ai/claude_sonnet_client.py` (`_real_file_call`/`_real_text_call`) — a cache hit never acquires a slot.

**Rationale:** Each job runs in its own subprocess (`web/worker.py`'s pool shells out to `scripts/run_full_pipeline.py` per job — see IC-19), so an in-process `threading.Semaphore` cannot coordinate across jobs claimed by different pool threads; this is why a cross-process, disk-based lock is used instead of a simpler in-memory primitive. Exists because `VIVE_WORKER_POOL_SIZE` (IC-19) can now run several jobs at once, each independently calling Claude Sonnet, which could otherwise exceed Azure Foundry's Claude Sonnet 4.6 deployment rate limit. **Known limitation, accepted by design rather than engineered around** (module's own docstring makes this explicit, same posture as `RISK_REGISTER.md` R-004's accepted stale-job gap): if a process holding a slot is killed outright (not a normal exception, which the `finally` block still cleans up after), that slot's lock file is never removed, and capacity is permanently reduced by one until the stale file is manually deleted from `lakehouse/ai_call_slots/`. See `discovery/RISK_REGISTER.md` R-010 for the risk writeup.

**Related invariant:** IC-19 (INV-05 in this document) governs *job claiming* (which jobs may run concurrently); this invariant governs a narrower resource (concurrent Claude Sonnet API calls) once jobs are already running — the two caps are independent and can each be sized differently (`VIVE_WORKER_POOL_SIZE` vs. `VIVE_MAX_CONCURRENT_AI_CALLS`).

**Current enforcement status:** YES, with one known, accepted limitation (see Rationale).

**Verified 2026-08-05 (Claude Code, direct trace):** `src/ai/concurrency_limiter.py:29,46,48` confirms `SLOT_DIR = lakehouse/ai_call_slots/`, `slot_{slot_id}.lock` naming, and `os.open(slot_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)`. Confirmed `_real_text_call`/file-call paths wrap only the actual API call in `with ai_call_slot():`; confirmed the cache-hit branch (`01_document_intake.py:668-678`) skips the AI client entirely, so `ai_call_slot()` is never invoked on a cache hit. Confirmed `web/worker.py:67-75` genuinely shells out via `subprocess.run([...scripts/run_full_pipeline.py...])` — not an in-process call — which is why the file-lock approach is necessary. Confirmed `discovery/RISK_REGISTER.md:190-200` contains R-010, severity Medium, "Mitigation (current): None automated."

**Caveat — stale-lock failure mode confirmed genuinely unmitigated:** `concurrency_limiter.py`'s cleanup only runs inside a `try/finally` (lines 69-75), which does **not** execute on a hard kill (`SIGKILL`, OS crash, `taskkill /F`). No `signal` import, `atexit` registration, or kill handler exists anywhere in the file. This is a real, currently-unaddressed gap, not a theoretical one — matches its own "known, accepted limitation" framing.

**This is never negotiable.**

---

## CQ-001 — Single-purpose functions, max two levels of nesting

**Scope:** GLOBAL

Each function, method, or handler must have a single stateable purpose. Conditional nesting exceeding two levels is a structural violation — refactor before proceeding.

**Note:** structural/style rule, not machine-verifiable by grep or trace — not included in the 2026-08-05 verification pass.

**This is never negotiable.**

---

## Engineer Sign-Off

**Status:** DRAFT — NOT YET REVIEWED

v1.2's prior claim of full review was found during BCE reconciliation (2026-07-27) to have no corresponding review record — reverted to draft pending actual engineer review.

**Verified 2026-08-05 (Claude Code, direct trace):** confirmed accurate — no formal review record exists anywhere in the repo (`discovery/`, git log, or the file's own history). The repo's own paper trail documents the correction: commit `a3359f0` ("BCE reconciliation: close out ENH-001 doc/code drift") states verbatim that it "Reverted docs/INVARIANTS.md's Engineer Sign-Off from an unverified 'REVIEWED AND CONFIRMED' claim (no corresponding review record found) back to honest draft status." No commit since `a3359f0` reintroduces a signed-off claim. `discovery/DOC_UPDATE_COMPARISON.md` and `discovery/ANNOTATION_CHECKLIST.md` corroborate the same conclusion. **Status below remains accurate and should stay as DRAFT until a real review actually happens — do not mark this reviewed without an actual engineer sign-off event.**

**Signature:** ______________________
**Date:** ______________________