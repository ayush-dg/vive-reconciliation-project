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
| v1.7 | 2026-08-06 | Ayush Kumar Sinha | **INV-02 amended: narrow Pass-3-only AI exception added.** Pass 1/Pass 2 remain 100% deterministic, unchanged, never negotiable. Pass 3 (Claude Sonnet 4.6 disambiguation) is now permitted under five explicit constraints matching the target architecture's D4/D5 design (`docs/target-architecture/VIVE_Statement_Reconciliation_Architecture_v3_1.md`): residual-only after Passes 1-2, ≤10-candidate SQL-retrieved set, schema-validated output only, never auto-approves at any confidence (`review_required` always `true`), confidence hard-capped at 0.85. No Pass 3 code was written as part of this change — this records the invariant ahead of implementation, per explicit instruction. **Recorded honestly: this is the engineer's (Ayush's) decision alone, made without the teammate/Sprint Lead's review — she is currently on leave. Provisional pending her confirmation on return; do not cite as joint or fully methodology-compliant sign-off until then.** |
| v1.8 | 2026-08-23 | Ayush Kumar Sinha (via Claude Code) | **INV-04 amended: `outstanding_amount` no longer required to be non-null in Silver.** `invoice_number` (or `ro_number` fallback) remains the only hard identifier requirement. Direct engineer instruction, confirmed explicitly after the conflict with the prior "never negotiable" wording was surfaced first. Motivated by "View Extracted Data" needing to show every row that reaches Bronze, including blank-amount payment/credit lines previously diverted straight to an `EXTRACTION_INCOMPLETE` exception before ever reaching Bronze. `write_missing_amount_exception()` removed (no remaining call sites); `get_skip_reason()` narrowed to identifier-only. See INV-04 for full basis and the implementation report for real before/after data. |

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

**Amended 2026-08-06:** The matching engine's Pass 1 and Pass 2 remain 100% deterministic — no AI model is ever consulted in these passes, for any reason. This invariant now permits a narrow, explicitly scoped exception for Pass 3 disambiguation only, matching the target architecture's D4/D5 design exactly (`docs/target-architecture/VIVE_Statement_Reconciliation_Architecture_v3_1.md`):
- Pass 3 may consult Claude Sonnet 4.6 ONLY on the residual left unresolved after Passes 1-2 (target: single-digit percent of lines at steady state).
- Pass 3 reads a SQL-retrieved candidate set capped at ≤10 records.
- Pass 3 output must pass schema validation before use; free-form AI text may never directly drive a match or accounting action.
- Pass 3 output NEVER auto-approves, at any confidence level — this is a permanent design constraint, not a threshold to be tuned. `review_required` must always be `true` for any Pass 3 result.
- Pass 3 confidence is hard-capped at 0.85, strictly below any auto-approve threshold in the system.
- Any implementation of Pass 3 that violates any of the above five constraints is out of scope for this amendment and would require a separate, new invariant decision.

**Basis for this amendment — recorded honestly:** this is the engineer's (Ayush's) decision, made 2026-08-06, WITHOUT the teammate/Sprint Lead's review — she is on leave at the time of this decision. This amendment should be treated as provisional until she confirms or revises it. Do not cite this as a joint or fully methodology-compliant sign-off until that confirmation happens.

**Prior wording (superseded 2026-08-06, kept for history):** "The matching engine makes every match/exception decision through deterministic rules only — no AI model is ever consulted inside the matching step, for any reason. `match_confidence` scoring is computed by deterministic rule (match type), not by an AI model."

**Current enforcement status:** Pass 1/Pass 2 — YES, confirmed (see verification below; predates this amendment). Pass 3 — NOT YET BUILT. This amendment records the invariant ahead of implementation; no Pass 3 code was written as part of this change, per explicit instruction.

**Verified 2026-08-05 (Claude Code, direct trace; predates this amendment, covers Pass 1/2 only):** `src/matching/engine.py`'s full import list is `json, os, sys, uuid, hashlib, datetime, src.lakehouse.connection, src.shop_owners` — zero AI/LLM imports. `score_match_confidence()` is a pure dictionary lookup keyed by match type, no network or model call.

**This is never negotiable** — Pass 1/2 determinism and each of the five Pass 3 constraints above are individually non-negotiable. This amendment narrows scope; it does not weaken enforcement.

---

## INV-03 — No totals/summary row may be ingested as an invoice line

**Scope:** GLOBAL

A vendor statement's grand-total, subtotal, or balance-forward row must never be extracted and validated as if it were a real invoice line.

**Current enforcement status:** PARTIAL — enforced in `pdfplumber_fallback.py` and `claude_sonnet_client.py` (active primary). Still absent in `GeminiClient`/`MistralClient` (both dormant, not a live risk).

**This is never negotiable.**

---

## INV-04 — `invoice_number` must never be null in Silver; `outstanding_amount` may be null (amended 2026-08-23)

**Scope:** GLOBAL

**Amended 2026-08-23:** `outstanding_amount` is no longer required to be non-null in Silver. Only `invoice_number` (or a fallback `ro_number` — see `get_skip_reason()`) remains a hard requirement for a row to reach Bronze/Silver. **Direct engineer instruction, explicitly confirmed** (Ayush Kumar Sinha, via Claude Code) after the conflict with the prior "never negotiable" wording below was surfaced and flagged before any code was written.

**Reason for the amendment:** a blank amount on the source document (e.g. a payment/credit line, or a genuinely blank Charges cell) was previously diverted straight to a `gold_exceptions` `EXTRACTION_INCOMPLETE` row before ever reaching Bronze — meaning "View Extracted Data" and Bronze itself never contained the row at all, undercounting the true raw extraction. The new rule: every extracted row with an invoice identifier reaches Bronze/Silver unconditionally, regardless of amount. Whether a blank-amount row is a genuine exception is now a decision for the matching engine (`src/matching/engine.py`) at reconciliation time, not for extraction to pre-empt.

**Current enforcement status:** YES, narrowed — enforced by a single-layer gate (`get_skip_reason()`, identifier-only). `validate_invoice()`'s `required_fields` no longer includes `outstanding_amount` (`config/validation/extraction_rules.json`).

**Verified 2026-08-23 (Claude Code, direct trace + real-data test):** `write_missing_amount_exception()` (the function that previously raised `EXTRACTION_INCOMPLETE` for a blank `outstanding_amount`) removed entirely — it has no remaining call sites. `get_skip_reason()`'s "no amount found" branch also removed; it now only checks for a missing invoice identifier (neither `invoice_number` nor `ro_number`). Confirmed against Fred Beans Lee's real data (117 previously-diverted blank-amount rows) — see the implementation report for exact before/after row counts.

**Historical note (pre-amendment, verified 2026-08-05):** prior to this change, enforcement was a two-layer gate — `get_skip_reason()`'s broad net (no identifier *and* no amount at all) plus `validate_invoice()`'s `required_fields` check (catching a row missing just one of the two fields). Both ran before `write_to_bronze()`.

**Caveat — application-level only, no database backstop (unchanged by this amendment):** `migrations/001_initial_schema.sql:61,69` declares `invoice_number TEXT` and `outstanding_amount REAL` **without `NOT NULL`**. The remaining identifier check does not touch the database either — a write path that bypassed `01_document_intake.py` (e.g. a direct SQL insert) would not be blocked by the schema itself.

**`invoice_number`-never-null remains never negotiable. The `outstanding_amount`-never-null clause is the one relaxed by this amendment — it is no longer in force.**

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