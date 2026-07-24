# INVARIANTS.md — VIVE Reconciliation

> **PBVI-009 Brownfield Onboarding — Approximation Notice**
> Produced without `pbvi_brownfield.md` (not available). This is a best-effort
> approximation, derived directly from `discovery/INVARIANT_CATALOGUE.md`'s 20
> cataloged invariants. `INVARIANT_AUTHORSHIP_MODE = GOVERNED` is the stated brownfield
> default per `pbvi_core.md` — under a real PBVI-009 run, the engineer authors this set
> first and signs off; here, CD selected and drafted the 5 candidates below for
> engineer review and adjudication. **Nothing here is final until reviewed.**

## Changelog
| Version | Date | Author | Change |
|---|---|---|---|
| v1.0 | 2026-07-24 | CD (approximated onboarding, draft) | Brownfield — Initial draft, 5 GLOBAL invariants selected from discovery/INVARIANT_CATALOGUE.md's 20 entries |
| v1.1 | 2026-07-24 | Ayush Kumar Sinha (engineer decision, direct instruction) | INV-05 narrowed from "at most one job PROCESSING system-wide" to "at most one job per distinct pdf_filename PROCESSING at a time," to enable web/worker.py's parallel worker pool (VIVE_WORKER_POOL_SIZE, default 3). See INV-05 below for full rationale. |

---

## Selection Rationale

`pbvi_core.md`'s Claude.md schema caps Section 2 (Hard Invariants) at **five GLOBAL
invariants, plus the mandatory CQ-001 complexity invariant** — this is a hard ceiling,
no override. The five below were selected from `discovery/INVARIANT_CATALOGUE.md`'s 20
cataloged invariants (IC-1 through IC-20) by severity of consequence if violated, not by
how well each is currently enforced — IC-15 in particular is included precisely because
it is *not* fully enforced today, and that gap is exactly what a hard invariant exists to
keep visible rather than let quietly slide further.

The remaining 15 invariants in `discovery/INVARIANT_CATALOGUE.md` are not demoted or
discarded — they remain TASK-SCOPED or lower-priority GLOBAL candidates, embedded in
individual task prompts as needed rather than carried in Claude.md's fixed 5-slot
ceiling. `discovery/INVARIANT_CATALOGUE.md` remains the complete, authoritative source.

---

## INV-01 — Confidence-gated human review

**Scope:** GLOBAL
**Source:** `discovery/INVARIANT_CATALOGUE.md` IC-15

Any row whose extraction confidence falls below the configured threshold (`0.60`) must
be routed to human review — never silently pass into Bronze/Silver as if it were a
fully-trusted extraction.

**Current enforcement status:** PARTIAL. The mechanical check always runs
(`notebooks/01_document_intake.py:validate_invoice()`), but is currently starved of a
genuine signal for `GeminiClient` and `MistralClient` (both dormant, not in the active
`provider_chain` — hardcode a flat `0.75` constant). Fixed for the active primary
(`ClaudeSonnetClient`) on 2026-07-24; see `discovery/RISK_REGISTER.md` R-001.

**This is never negotiable.**

---

## INV-02 — Matching is 100% deterministic, zero AI involvement

**Scope:** GLOBAL
**Source:** `discovery/INVARIANT_CATALOGUE.md` IC-3

The matching engine (`src/matching/engine.py`) makes every match/exception decision
through deterministic rules only — no AI model is ever consulted inside the matching
step, for any reason.

**Current enforcement status:** YES — confirmed no import of, or call into, any AI
client anywhere in the matching module.

**This is never negotiable.**

---

## INV-03 — No totals/summary row may be ingested as an invoice line

**Scope:** GLOBAL in intent
**Source:** `discovery/INVARIANT_CATALOGUE.md` IC-20

A vendor statement's grand-total, subtotal, or balance-forward row must never be
extracted and validated as if it were a real invoice line — doing so silently corrupts
the statement total and the reconciliation itself.

**Current enforcement status:** PARTIAL — enforced in `pdfplumber_fallback.py` (and, by
inheritance, `document_intelligence_client.py`) and, as of 2026-07-24, in the active
primary (`claude_sonnet_client.py`). Still absent in `GeminiClient`/`MistralClient`
(both dormant). See `discovery/RISK_REGISTER.md` R-002.

**This is never negotiable.**

---

## INV-04 — `invoice_number` and `outstanding_amount` must never be null in Silver

**Scope:** GLOBAL
**Source:** `discovery/INVARIANT_CATALOGUE.md` IC-14

Every row written to the Silver layer must carry both an invoice identifier and an
amount — the matching engine depends on both fields being present for every row it
processes.

**Current enforcement status:** YES — enforced by a two-layer gate
(`get_skip_reason()`'s broad skip plus `validate_invoice()`'s `required_fields` check).

**This is never negotiable.**

---

## INV-05 — At most one job per `pdf_filename` may be in `PROCESSING` status at a time

**Scope:** GLOBAL
**Source:** `discovery/INVARIANT_CATALOGUE.md` IC-19 (as narrowed below, 2026-07-24)

**Amended 2026-07-24, by direct engineer instruction (Ayush Kumar Sinha), to enable
`web/worker.py`'s parallel worker pool (a pool was pointless under the original
wording — see below).** Original wording: "the background job worker must never allow
two jobs to be claimed and processed concurrently, system-wide, for any reason." That
was broader than the actual failure mode it existed to prevent: two jobs for the SAME
PDF racing the same `extraction_cache` row, each missing the other's write and both
re-running the full (~5 minute) AI extraction. The amended invariant keeps exactly that
protection — same-`pdf_filename` jobs still can never be claimed and processed
concurrently — while allowing genuinely different statements to process in parallel, up
to `WORKER_POOL_SIZE` (`VIVE_WORKER_POOL_SIZE` env var, default 3) at once, each
independently rate-limited against Claude Sonnet's Azure Foundry deployment via
`src/ai/concurrency_limiter.py` (`VIVE_MAX_CONCURRENT_AI_CALLS`, default 2).

**Current enforcement status:** YES — enforced by a single atomic `UPDATE ... WHERE ...
NOT EXISTS (SELECT 1 FROM jobs busy WHERE busy.status = 'PROCESSING' AND
busy.pdf_filename = p.pdf_filename)` guard (`web/queries.py:claim_next_pending_job()`).
Note: this same guard is what makes the still-missing stale-job-requeue logic
(`discovery/RISK_REGISTER.md` R-004) a point of stall for that one filename's future
jobs if ever violated by a hung job — no longer a stall for the entire queue, since
other filenames can still be claimed and processed around it.

**This is never negotiable — for the amended (per-filename) statement above. The
original system-wide statement no longer holds; do not revert to it without another
explicit engineer decision.**

---

## Engineer Sign-Off

**Status:** DRAFT — NOT YET REVIEWED

[ ] I have reviewed the 5 invariants above against my own operational knowledge of
    this system and confirm they are the correct GLOBAL set for `Claude.md`.

**Signature:** ______________________
**Date:** ______________________
