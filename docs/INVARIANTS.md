# INVARIANTS.md — VIVE Reconciliation
Updated: 2026-07-27

## Changelog
| Version | Date | Author | Change |
|---|---|---|---|
| v1.0 | 2026-07-24 | CD | Initial draft, 5 GLOBAL invariants |
| v1.1 | 2026-07-24 | Ayush Kumar Sinha | INV-05 narrowed to per-filename (not system-wide) to enable parallel worker pool |
| v1.2 | 2026-07-27 | Ayush Kumar Sinha | Updated enforcement status for all invariants to reflect current build state |

---

## INV-01 — Confidence-gated human review

**Scope:** GLOBAL

Any row whose extraction confidence falls below the configured threshold (`0.60`) must be routed to human review — never silently pass into Bronze/Silver as if it were a fully-trusted extraction. Rows that fail this gate are written to `validation_document_review_queue` with `rejection_category = MISSING_MANDATORY_FIELD` or handled via the row-skip path depending on failure mode.

**Current enforcement status:** PARTIAL. The mechanical check always runs (`notebooks/01_document_intake.py:validate_invoice()`). Claude Sonnet 4.6 (active primary) was fixed 2026-07-24 — it now returns a genuine per-row confidence value instead of the old hardcoded `0.75` constant. `GeminiClient` and `MistralClient` remain broken but dormant, still hardcoding `0.75`. `match_confidence` (a separate field on `gold_matched_invoices` and `gold_exceptions`) is now genuine, but that is a different signal from extraction confidence.

**This is never negotiable.**

---

## INV-02 — Matching is 100% deterministic, zero AI involvement

**Scope:** GLOBAL

The matching engine makes every match/exception decision through deterministic rules only — no AI model is ever consulted inside the matching step, for any reason. `match_confidence` scoring is computed by deterministic rule (match type), not by an AI model.

**Current enforcement status:** YES — confirmed. No import of, or call into, any AI client anywhere in the matching module.

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

**This is never negotiable.**

---

## INV-05 — At most one job per `pdf_filename` may be in PROCESSING status at a time

**Scope:** GLOBAL

**Amended 2026-07-24:** Original wording was "at most one job PROCESSING system-wide." Narrowed by direct engineer instruction to enable the parallel worker pool. Two jobs for the SAME PDF must never be claimed and processed concurrently (they race the same `extraction_cache` row). Different filenames MAY process concurrently, up to `WORKER_POOL_SIZE` (default 3).

**Current enforcement status:** YES — enforced by atomic `UPDATE ... WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE status = 'PROCESSING' AND pdf_filename = ?)` guard in `web/queries.py:claim_next_pending_job()`. Race condition fix committed as `dc7e64a`.

**This is never negotiable for the per-filename statement. Do not revert to the system-wide statement without an explicit engineer decision.**

---

## INV-06 — No more than `VIVE_MAX_CONCURRENT_AI_CALLS` Claude Sonnet extraction calls may run concurrently system-wide

**Scope:** GLOBAL

**Source:** Code-observed only — added 2026-07-25, following the worker-pool change that made this cap necessary.

**Enforcement point:** `src/ai/concurrency_limiter.py:ai_call_slot()` — a cross-process file-lock semaphore (`lakehouse/ai_call_slots/slot_0.lock` … `slot_{N-1}.lock`, exclusive-create via `os.O_CREAT | os.O_EXCL`, atomic on both POSIX and Windows). Wraps only the real network call in `src/ai/claude_sonnet_client.py` (`_real_file_call`/`_real_text_call`) — a cache hit never acquires a slot.

**Rationale:** Each job runs in its own subprocess (`web/worker.py`'s pool shells out to `scripts/run_full_pipeline.py` per job — see IC-19), so an in-process `threading.Semaphore` cannot coordinate across jobs claimed by different pool threads; this is why a cross-process, disk-based lock is used instead of a simpler in-memory primitive. Exists because `VIVE_WORKER_POOL_SIZE` (IC-19) can now run several jobs at once, each independently calling Claude Sonnet, which could otherwise exceed Azure Foundry's Claude Sonnet 4.6 deployment rate limit. **Known limitation, accepted by design rather than engineered around** (module's own docstring makes this explicit, same posture as `RISK_REGISTER.md` R-004's accepted stale-job gap): if a process holding a slot is killed outright (not a normal exception, which the `finally` block still cleans up after), that slot's lock file is never removed, and capacity is permanently reduced by one until the stale file is manually deleted from `lakehouse/ai_call_slots/`. See `discovery/RISK_REGISTER.md` R-010 for the risk writeup.

**Related invariant:** IC-19 (INV-05 in this document) governs *job claiming* (which jobs may run concurrently); this invariant governs a narrower resource (concurrent Claude Sonnet API calls) once jobs are already running — the two caps are independent and can each be sized differently (`VIVE_WORKER_POOL_SIZE` vs. `VIVE_MAX_CONCURRENT_AI_CALLS`).

**Current enforcement status:** YES, with one known, accepted limitation (see Rationale).

**This is never negotiable.**

---

## CQ-001 — Single-purpose functions, max two levels of nesting

**Scope:** GLOBAL

Each function, method, or handler must have a single stateable purpose. Conditional nesting exceeding two levels is a structural violation — refactor before proceeding.

**This is never negotiable.**

---

## Engineer Sign-Off

**Status:** DRAFT — NOT YET REVIEWED

v1.2's prior claim of full review was found during BCE reconciliation (2026-07-27) to have no corresponding review record — reverted to draft pending actual engineer review.

**Signature:** ______________________
**Date:** ______________________
