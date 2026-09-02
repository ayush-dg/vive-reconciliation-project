STAGE-1-DRAFT: DOCS-DERIVED — 2026-09-01 — Produced by BCE Adapter Pipeline Stage 1

# INVARIANT_CATALOGUE.md — VIVE Statement Reconciliation

Source: `docs/INVARIANTS.md` v1.7. **ID convention note:** the BCE template's default
`IC-[N]` numbering (matching a source `INV-[N]` scheme) doesn't fit this project — its own
`INVARIANTS.md` uses a native `G`/`S`/`T` prefix scheme, not `INV-N`. IDs below preserve
that native scheme directly (G1–G5, S1–S11) rather than introducing a parallel renumbering
that would only add confusion. T1–T7 are excluded — explicitly deferred/BCE-scope, not
enforced by this bounded build (`ARCHITECTURE.md` §7 Parking Lot), so there is nothing yet
to catalogue for them; they remain in `INVARIANTS.md` itself as the target-state reference.

**"Currently enforced" is marked NOT DETERMINABLE FROM SOURCE for every entry below,
unconditionally** — this is a Stage 1 rule, not a per-invariant judgment: confirming actual
enforcement requires reading source code (Stage 2). Note that
`verification/VERIFICATION_CHECKLIST.md` (Phase 8 Part 1, 2026-09-01) already provides
real, run-confirmed enforcement evidence for most of these from *outside* this pipeline —
cited per entry below as a cross-reference, not substituted for the Stage 1 rule itself.

---

- **ID:** G1
- **Statement:** `ExtractionAttempt.document_id` always references a valid Document. Once
  written, an extraction attempt record is never modified — a subsequent attempt is a new
  record, not an update to a prior one. Applies to every table in the `extracted` schema
  holding raw extraction output (the single `extracted.extraction_attempt` log, and every
  per-vendor `extracted.stmt_<vendor_slug>` raw table).
- **Category:** Data Correctness
- **Scope:** GLOBAL
- **Why it matters:** loss of the audit trail G2/S10 depend on; an attempt history that can
  be silently rewritten undermines the arithmetic-gate audit record entirely.
- **Currently enforced:** NOT DETERMINABLE FROM SOURCE
- **Source:** `INVARIANTS.md` states Detection point = FK constraint (document_id);
  append-only enforcement at the write layer (no UPDATE permitted on attempt rows).
  Cross-reference: `VERIFICATION_CHECKLIST.md` records this as Automated/PASS via Task
  3.1's `test_extraction_attempt_recording.sh` (first clean run).

- **ID:** G2
- **Statement:** A document is never eligible for matching unless its latest extraction has
  passed structural validation (invoice_number, or ro_number fallback, present) and
  arithmetic validation. The extraction-confidence floor is not part of this gate —
  confidence is diagnostic metadata only, never a pass/fail input.
- **Category:** Data Correctness
- **Scope:** GLOBAL
- **Why it matters:** the pipeline's highest-value control for the failure modes it still
  catches — a violation silently poisons every downstream task (matching, exceptions,
  reporting) with corrupted data.
- **Currently enforced:** NOT DETERMINABLE FROM SOURCE
- **Source:** `INVARIANTS.md` states Detection point = validation gate check at the
  Silver-promotion boundary. Cross-reference: `VERIFICATION_CHECKLIST.md` records
  Automated/PASS via Task 3.2's `test_validation_gate.sh` and Task 9.7's umbrella
  known-vendor-extractor script, both clean runs.

- **ID:** G3
- **Statement:** Vendor/document content supplied to Claude must be treated strictly as
  input data. Extracted content must never be concatenated into or allowed to modify the
  model's instructions.
- **Category:** Security
- **Scope:** GLOBAL
- **Why it matters:** security-critical, applies wherever any LLM call exists in the
  system; a violation produces silently corrupted extraction that passes all downstream
  checks.
- **Currently enforced:** NOT DETERMINABLE FROM SOURCE
- **Source:** `INVARIANTS.md` states Detection point = code review checklist;
  prompt-template structural separation at the API-call layer. Cross-reference:
  `VERIFICATION_CHECKLIST.md` records Automated/PASS via Task 3.4's
  `test_prompt_injection_defense.sh` and Task 5.3's `test_ai_residual_matching.sh`
  (also covers the AI-write-authority non-negotiable — AI never auto-approves).

- **ID:** G4
- **Statement:** Byte-identical documents, identified by the same content hash, are never
  independently re-extracted or re-matched.
- **Category:** Data Correctness / Operational
- **Scope:** GLOBAL
- **Why it matters:** document identity is a foundational assumption every downstream
  component relies on.
- **Currently enforced:** NOT DETERMINABLE FROM SOURCE
- **Source:** `INVARIANTS.md` states Detection point = unique constraint on
  `content_sha256` at write time. Cross-reference: `VERIFICATION_CHECKLIST.md` records
  Automated/PASS via Task 2.2's `test_document_registration.sh` and `upload.spec.ts`'s
  dedicated G4 UI test.

- **ID:** G5
- **Statement:** A document/work item cannot have multiple active processing owners
  simultaneously. A retry or re-trigger must acquire processing ownership before execution;
  an already-owned item must not be processed concurrently.
- **Category:** Operational
- **Scope:** GLOBAL
- **Why it matters:** spans both extraction and matching workers; a concurrency violation
  causes duplicated Claude API spend and conflicting state writes.
- **Currently enforced:** NOT DETERMINABLE FROM SOURCE
- **Source:** `INVARIANTS.md` states Detection point = atomic processing-ownership
  acquisition at trigger — Task 2.4's `UPDATE ... WHERE status != 'Processing'` guard
  (extraction), Task 5.1's per-document row lock (matching). Cross-reference:
  `VERIFICATION_CHECKLIST.md` records Automated/PASS overall, with one non-reproducing
  flaky failure noted (isolated-spec-run `ECONNRESET`, passed on full-suite re-run — not
  counted as a genuine result).

- **ID:** S1
- **Statement:** Upload/intake never implicitly triggers matching. Uploading a document may
  trigger extraction (per D-I) but never directly causes a matching execution.
- **Category:** Operational
- **Scope:** TASK-SCOPED
- **Currently enforced:** NOT DETERMINABLE FROM SOURCE
- **Source:** `INVARIANTS.md` Scope = intake and match-trigger tasks. Cross-reference:
  `VERIFICATION_CHECKLIST.md` records Automated/PASS (covered within Task 2.2's script and
  `extract-trigger.spec.ts`).

- **ID:** S2
- **Statement:** A non-identical document for an already-processed vendor/period/entity is
  version-chained automatically, not silently duplicated or flagged for human review
  (amended 2026-08-26 — no human checkpoint).
- **Category:** Data Correctness
- **Scope:** TASK-SCOPED
- **Currently enforced:** NOT DETERMINABLE FROM SOURCE
- **Source:** `INVARIANTS.md` Scope = document intake / version-resolution tasks.
  Cross-reference: `VERIFICATION_CHECKLIST.md` records Automated/PASS
  (`upload.spec.ts`'s re-upload/dedup tests).

- **ID:** S3
- **Statement:** Reporting reads from the designated ReportView/Gold-equivalent surface and
  never joins or queries transactional `recon` tables directly.
- **Category:** Integration
- **Scope:** TASK-SCOPED
- **Currently enforced:** NOT DETERMINABLE FROM SOURCE
- **Source:** `INVARIANTS.md` Scope = report-building task. Cross-reference:
  `VERIFICATION_CHECKLIST.md` marks this **N/A this build** — no reporting surface
  currently exists to exercise the check (Session 7/Gold integration removed by engineer
  direction); Home's current summary stats read `recon`/`extracted` directly, a known
  deliberate interim state distinct from any future ReportView implementation.

- **ID:** S4
- **Statement:** A document is never registered without a legal-entity assignment
  (`legal_entity_id`).
- **Category:** Data Correctness
- **Scope:** TASK-SCOPED
- **Currently enforced:** NOT DETERMINABLE FROM SOURCE
- **Source:** `INVARIANTS.md` Scope = document schema / ingestion task. Cross-reference:
  `VERIFICATION_CHECKLIST.md` records this indirectly via `npm run test:schema`'s TC-2
  (NULL `legal_entity_id` rejected) — that script's clean-run portion passed before hitting
  an unrelated vendor-registry idempotency error on a later, unrelated sub-check.

- **ID:** S5
- **Statement:** `Exception.category` uses a fixed, approved set of categories and is never
  free text.
- **Category:** Data Correctness
- **Scope:** TASK-SCOPED
- **Currently enforced:** NOT DETERMINABLE FROM SOURCE
- **Source:** `INVARIANTS.md` Scope = exception schema / matching / exception-handling
  tasks. Cross-reference: `VERIFICATION_CHECKLIST.md` records Automated/PASS via Task 5.4's
  `test_exception_schema_wiring.sh` and `exceptions.spec.ts`'s dedicated "no
  possible_duplicate_correction category ever appears" test.

- **ID:** S6
- **Statement:** If normalization rules change, historical matching can still identify
  which normalization version produced a given `silver.statement_line` row.
- **Category:** Operational
- **Scope:** TASK-SCOPED
- **Currently enforced:** NOT DETERMINABLE FROM SOURCE
- **Source:** `INVARIANTS.md` Scope = normalization implementation task. Cross-reference:
  `VERIFICATION_CHECKLIST.md` records Automated/PASS via Task 3.6's
  `test_silver_normalization.sh`.

- **ID:** S7
- **Statement:** A document receives at most two extraction attempts (amended 2026-08-26);
  a document repeatedly submitted beyond that bound is a violation.
- **Category:** Operational
- **Scope:** TASK-SCOPED
- **Currently enforced:** YES — [STAGE-2-UPDATE — 2026-09-02] confirmed directly against
  source (overrides the blanket Stage 1 "NOT DETERMINABLE" rule for this one entry, since
  Stage 2 reading has now actually settled it; see Source below for what happened).
- **Enforcement point:** `src/lib/documentStatus.ts:139-165` (`computeDocumentStatus`,
  M-012 per `discovery/components/A02_module_call_map.md`)
- **Source:** `INVARIANTS.md` Scope = extraction service task. Cross-reference:
  `VERIFICATION_CHECKLIST.md` originally recorded a FAIL here (13/14 sub-checks passed;
  one display-layer assertion failed). **[STAGE-2-UPDATE — 2026-09-02]:** confirmed via
  direct source reading (`src/lib/documentStatus.ts:155-158`, cross-checked by two
  independent module-contract sessions, B and C) that this was a **false positive** — the
  code correctly returns a distinct `'Extracted'` badge for this exact case (added
  2026-08-31 by engineer direction specifically to disambiguate it from `'Processing'`);
  the test at `scripts/test_bounded_retry.mjs:58` asserts the pre-2026-08-31 expectation
  and was never updated. `VERIFICATION_CHECKLIST.md` has been corrected accordingly. The
  stale test assertion itself remains unfixed.

- **ID:** S8
- **Statement:** Every Match and Exception that depends on reference data must carry the
  version/provenance of that reference data (amended 2026-08-28 — satisfied by capturing
  `_run_id`/`_extracted_at`/`_source_system` at match time, not a built snapshot
  mechanism).
- **Category:** Data Correctness / Integration
- **Scope:** TASK-SCOPED
- **Currently enforced:** NOT DETERMINABLE FROM SOURCE
- **Source:** `INVARIANTS.md` Scope = matching service task. Cross-reference:
  `VERIFICATION_CHECKLIST.md` records Automated/PASS via Task 5.2's
  `test_deterministic_matching.sh`.

- **ID:** S10
- **Statement:** Every extraction attempt is written to the `extracted` schema before
  validation occurs, never the reverse (reworded 2026-08-27, was "Bronze write precedes
  validation").
- **Category:** Operational
- **Scope:** TASK-SCOPED
- **Currently enforced:** NOT DETERMINABLE FROM SOURCE
- **Source:** `INVARIANTS.md` Scope = extraction service task. Cross-reference:
  `VERIFICATION_CHECKLIST.md` records Automated/PASS (covered within Task 3.1's clean
  script run).

- **ID:** S11
- **Statement:** Once a StatementLine's amount is extracted and written to Silver, it is
  immutable — never updated in place without a new version.
- **Category:** Data Correctness
- **Scope:** TASK-SCOPED
- **Currently enforced:** NOT DETERMINABLE FROM SOURCE
- **Source:** `INVARIANTS.md` Scope = extraction / Silver-write task. Cross-reference:
  `VERIFICATION_CHECKLIST.md` marks this **NOT INDEPENDENTLY VERIFIED** — no dedicated
  automated check was found or run for this specific invariant; it holds by architectural
  absence (no UPDATE code path was found in the reviewed scripts) but was not behaviorally
  exercised.

- **ID:** S12 (candidate, not yet formally added to `INVARIANTS.md`)
- **Statement:** NOT DETERMINABLE FROM SOURCE — no statement exists yet; `EXECUTION_PLAN.md`
  Task 8.5's own text says "Invariant enforcement: TBD — engineer to decide whether this
  warrants a new task-scoped invariant (e.g. S12) or stays an unenforced implementation
  detail," describing row-level duplicate detection (invoice number + amount).
- **Category:** Data Correctness (tentative, based on the candidate's described purpose)
- **Scope:** NOT DETERMINABLE FROM SOURCE (not yet assigned)
- **Currently enforced:** NOT DETERMINABLE FROM SOURCE
- **Source:** `EXECUTION_PLAN.md` Task 8.5. Cross-reference: `VERIFICATION_CHECKLIST.md`
  records this task's verification script was never committed, and even the manual check
  that was attempted was incomplete (no real duplicate line existed in any tested
  document). Listed here as an open engineer decision, not a confirmed invariant — flagged
  for the Stage 3 Annotation Checklist as an OPEN_QUESTION, not a contradiction.
