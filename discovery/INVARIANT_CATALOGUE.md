STAGE-1-DRAFT: DOCS-DERIVED — 2026-09-01 — Produced by BCE Adapter Pipeline Stage 1
STAGE-2-STATUS: COMPLETE — 2026-09-02, BCE Adapter Pipeline Stage 2 Session D (implicit
invariant walkthrough). PART 1: all 16 entries (G1-G5, S1-S11, S12-candidate) given a real
Enforcement point / Owning module / Enforcing modules against source, and "Currently
enforced" flipped from the blanket Stage 1 NOT DETERMINABLE to an actual determination for
every entry. One STAGE-2-DIVERGENCE found and tagged (S7's prior Enforcement point
attribution). PART 2: 3 new implicit invariant candidates (IC-CANDIDATE-01..03) appended
below, including a lock-recovery invariant distinct from G5 itself; the exception-write
idempotency question was explicitly considered and NOT elevated (see rationale in the new
section).

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
- **Currently enforced:** YES — [STAGE-2-CONFIRMED — 2026-09-02] `runExtractionPipeline`
  (`src/lib/extractionPipeline.ts:118-132`) unconditionally `INSERT`s one
  `extracted_extraction_attempt` row per attempt before any retry decision is made
  (comment at line 84-87 cites S10/G1 explicitly). A codebase-wide grep for `UPDATE` against
  `extracted_extraction_attempt` or any `extracted_stmt_*` table returned zero hits — the
  only `UPDATE` anywhere against a `recon_*`/`extracted_*` table is
  `exceptionDetail.ts:158`'s unrelated `recon_exception` resolution-status update — so
  append-only holds by confirmed architectural absence, not merely by assumption.
- **Enforcement point:** `src/lib/extractionPipeline.ts:118-132` (`runExtractionPipeline`)
- **Owning module:** M-022
- **Enforcing modules:** M-022 (sole writer of `extracted_extraction_attempt` and every
  per-vendor `extracted_stmt_<vendor_slug>` raw table — the latter written at
  `extractionPipeline.ts:137-142`, also INSERT-only)
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
- **Currently enforced:** YES — [STAGE-2-CONFIRMED — 2026-09-02] The real gate is the `if
  (arithmeticPass && structuralPass && extracted && vendor)` check at
  `extractionPipeline.ts:145`, guarding the sole call to `normalizeToSilver` — a document
  whose latest attempt fails either check never gets a `silver_statement_line` row at all.
  Matching (`matchingPipeline.ts`'s `getEligibleLinesForDocument`) only ever selects from
  `silver_statement_line`, so a document that never reached Silver is structurally
  unreachable by matching — the gate is enforced by absence downstream, not by a
  matching-side re-check. Confidence is confirmed never part of this gate:
  `validationGate.ts` computes `arithmeticPass`/`structuralPass` from `reasonCodes`
  (`ARITHMETIC_MISMATCH`, `MISSING_IDENTIFIER`) only — `confidence` is a separate field on
  `ExtractionOutcome`, never read by `validateExtraction`.
- **Enforcement point:** `src/lib/extractionPipeline.ts:145` (the pre-`normalizeToSilver`
  gate check)
- **Owning module:** M-022
- **Enforcing modules:** M-022 (gate check), M-023 (`validationGate.ts` — computes the
  pass/fail this gate reads), M-024 (`silverNormalization.ts` — trusts the gate, writes
  nothing itself if never called), M-025 (`matchingPipeline.ts` — only queries
  `silver_statement_line`, so ineligible documents are invisible to it by construction)
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
- **Currently enforced:** YES — [STAGE-2-CONFIRMED — 2026-09-02] Two independent Claude
  call sites both enforce structural separation: `aiProvider.ts`'s `EXTRACTION_SYSTEM_PROMPT`
  (lines 67-79) is a fixed constant, and `buildExtractionRequest` (lines 190-216) passes
  document bytes as a `document` content block (`source.type: 'base64'`) — never
  concatenated into `system`. `aiResidualMatching.ts`'s `RESIDUAL_SYSTEM_PROMPT` (line 76)
  is likewise fixed, and `proposeActionViaClaudeLive` (lines 99-128) passes the statement
  line + CCC data as `JSON.stringify`'d text content, not instruction text. Both prompts
  additionally instruct the model explicitly to treat embedded instruction-like text as
  data, not commands. Per the Module Contracts index (M-027's finding), this is genuinely
  two separate, independently-maintained enforcement sites, not one shared path — a future
  change to one's discipline would not automatically apply to the other.
- **Enforcement point:** `src/lib/aiProvider.ts:67-79,190-216` (`EXTRACTION_SYSTEM_PROMPT`,
  `buildExtractionRequest`)
- **Owning module:** M-028
- **Enforcing modules:** M-028 (extraction call), M-027 (`aiResidualMatching.ts` — its own
  independent enforcement, `RESIDUAL_SYSTEM_PROMPT` + JSON-structured content, not routed
  through M-028)
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
- **Currently enforced:** YES — [STAGE-2-CONFIRMED — 2026-09-02] `registerDocument`
  (`src/lib/documents.ts:90-126`) checks `findDocumentByHash` first (clean no-op path), and
  the `content_sha256 NVARCHAR(64) NOT NULL UNIQUE` DB constraint
  (`migrations/001_foundation_schema.sql:42,48`) is the real backstop — the function's own
  `catch` block string-matches `UNIQUE constraint failed` and turns a check-then-insert race
  into the same graceful duplicate response, per its own doc comment.
- **Enforcement point:** `src/lib/documents.ts:90-126` (`registerDocument`)
- **Owning module:** M-011
- **Enforcing modules:** M-011 (app-layer pre-check + race backstop); the DB-level UNIQUE
  constraint itself (`migrations/001_foundation_schema.sql`) is the ultimate guarantee but
  is schema DDL, not a module
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
- **Currently enforced:** YES for the core "no concurrent double-processing" guarantee —
  [STAGE-2-CONFIRMED — 2026-09-02] Both mechanisms are genuinely atomic single-statement
  guards, not read-then-write races: `extraction.ts:36-38`'s
  `UPDATE extracted_document SET status='processing' WHERE document_id=? AND status !=
  'processing'` (rejects a second trigger outright if `changes === 0`), and
  `matchingInvocation.ts:48-58`'s `acquireMatchingLock` (`INSERT ... ON CONFLICT DO UPDATE
  ... WHERE acquired_at < staleness-window`, returning `false` unless exactly one row
  changed). **However, this is two independently-implemented mechanisms, not one shared
  enforcement path** — see IC-CANDIDATE-01 below for a distinct, NOT-fully-enforced
  implicit invariant this split exposes (crash-recoverability of the lock), which G5's own
  statement does not itself require.
- **Enforcement point:** `src/lib/extraction.ts:36-38` (`triggerExtraction`) and
  `src/lib/matchingInvocation.ts:48-58` (`acquireMatchingLock`) — two separate mechanisms,
  no single enforcement point
- **Owning module:** M-015 (extraction lock, earliest/Task 2.4 implementation) and M-017
  (matching lock, Task 5.1) — genuinely dual-owned, not reducible to one module
- **Enforcing modules:** M-015, M-017 (serving-layer lock logic), M-046, M-047 (route-layer
  callers that invoke the above — no independent lock logic of their own)
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
- **Currently enforced:** YES — [STAGE-2-CONFIRMED — 2026-09-02] Confirmed by architectural
  absence: `A02_module_call_map.md`'s Internal Call Table shows `documents.ts` (M-011,
  registration) calling only M-003/M-005/M-012 — no edge to M-017/M-025 (matching) exists
  anywhere in the traced call graph. Each of the three relevant modules also states the
  invariant in its own doc comment (`documents.ts:10`, `extraction.ts:5-6`,
  `matchingInvocation.ts:19`).
- **Enforcement point:** absence of any call edge from `src/lib/documents.ts` to
  `src/lib/matchingInvocation.ts`/`matchingPipeline.ts` (confirmed via
  `discovery/components/A02_module_call_map.md`'s Internal Call Table)
- **Owning module:** M-011
- **Enforcing modules:** M-011, M-015, M-017 (each independently documents and upholds the
  non-connection; no shared guard mechanism, just the absence of a call)
- **Source:** `INVARIANTS.md` Scope = intake and match-trigger tasks. Cross-reference:
  `VERIFICATION_CHECKLIST.md` records Automated/PASS (covered within Task 2.2's script and
  `extract-trigger.spec.ts`).

- **ID:** S2
- **Statement:** A non-identical document for an already-processed vendor/period/entity is
  version-chained automatically, not silently duplicated or flagged for human review
  (amended 2026-08-26 — no human checkpoint).
- **Category:** Data Correctness
- **Scope:** TASK-SCOPED
- **Currently enforced:** YES — [STAGE-2-CONFIRMED — 2026-09-02] `runVersionChaining`
  (`vendorIdentification.ts:135-156`) finds the prior document matching
  vendor/period/entity with `is_latest_version = 1`, and — inside one `db.transaction` —
  flips the prior row's `is_latest_version` to 0 and sets the new document's
  `previous_statement_id`/`is_latest_version = 1`. No human-review flag is ever set (no such
  column is touched here). Called automatically from `identifyAndExtract` once
  vendor/period are known — never gated behind any manual step. Re-entrancy checked: since
  chaining flips the prior document's `is_latest_version` to 0 as part of the same
  transaction, a second call for the same new document (e.g. across the 2 retry attempts
  S7 allows) finds no more `is_latest_version = 1` prior to chain against — self-guarding
  against a double-chain, not merely "probably fine."
- **Enforcement point:** `src/lib/vendorIdentification.ts:135-156` (`runVersionChaining`)
- **Owning module:** M-021
- **Enforcing modules:** M-021 (chaining logic), M-022 (`extractionPipeline.ts` — calls
  `identifyAndExtract`, the only path that reaches `runVersionChaining`)
- **Source:** `INVARIANTS.md` Scope = document intake / version-resolution tasks.
  Cross-reference: `VERIFICATION_CHECKLIST.md` records Automated/PASS
  (`upload.spec.ts`'s re-upload/dedup tests).

- **ID:** S3
- **Statement:** Reporting reads from the designated ReportView/Gold-equivalent surface and
  never joins or queries transactional `recon` tables directly.
- **Category:** Integration
- **Scope:** TASK-SCOPED
- **Currently enforced:** N/A THIS BUILD — [STAGE-2-CONFIRMED — 2026-09-02] Confirmed no
  ReportView/Gold-equivalent surface exists anywhere in `src/` (no module in the roster is
  described as one, and Session 7/Gold was formally removed per
  `pbvi_session7_deferred.md`). `homeSummary.ts` (M-014)'s `getHomeSummaryStats`
  (`src/lib/homeSummary.ts:24-46`) queries `recon_exception` and `recon_match` directly by
  table name, and transitively `extracted_document` via M-011 — this is a real, confirmed
  direct-table read, but S3 scopes itself explicitly to "report-building task," which this
  build never implements; Home's stats are not standing in as that surface, they are a
  separate, acknowledged interim design. Not tagged STAGE-2-DIVERGENCE since Stage 1's own
  cross-reference already recorded this exact same N/A/interim-state characterization —
  source reading confirms it rather than contradicting it.
- **Enforcement point:** none — no ReportView/Gold-equivalent surface exists in this build
  to enforce the invariant on
- **Owning module:** N/A (not yet built)
- **Enforcing modules:** none. (For contrast/traceability only, not as a violation: M-014
  reads `recon_exception`/`recon_match` directly — exactly the pattern S3 would forbid IF
  M-014 were the designated reporting surface, which it is explicitly documented not to be.)
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
- **Currently enforced:** YES — [STAGE-2-CONFIRMED — 2026-09-02] DB-level:
  `legal_entity_id NOT NULL` in both dialect DDLs
  (`migrations/001_foundation_schema.sql:40` SQLite, `:49` Fabric, the SQLite line
  explicitly comment-tagged `-- S4: legal_entity_id NOT NULL (DB-enforced)`). App-level
  backstop: `registerDocument(fileBytes, legalEntityId, ...)`
  (`src/lib/documents.ts:90`) takes `legalEntityId` as a required (non-optional) parameter
  and is the sole write path into `extracted_document`.
- **Enforcement point:** `migrations/001_foundation_schema.sql:40,49` (DDL `NOT NULL`
  constraint); app-layer backstop at `src/lib/documents.ts:90` (`registerDocument`)
- **Owning module:** M-011
- **Enforcing modules:** M-011 (sole INSERT path), M-007 (`migrate.ts` — applies the SQLite
  migration that defines the constraint; Fabric's DDL is applied externally per
  `EXECUTION_PLAN.md` Task 1.2, not by any module in the request-serving call graph)
- **Source:** `INVARIANTS.md` Scope = document schema / ingestion task. Cross-reference:
  `VERIFICATION_CHECKLIST.md` records this indirectly via `npm run test:schema`'s TC-2
  (NULL `legal_entity_id` rejected) — that script's clean-run portion passed before hitting
  an unrelated vendor-registry idempotency error on a later, unrelated sub-check.

- **ID:** S5
- **Statement:** `Exception.category` uses a fixed, approved set of categories and is never
  free text.
- **Category:** Data Correctness
- **Scope:** TASK-SCOPED
- **Currently enforced:** YES — [STAGE-2-CONFIRMED — 2026-09-02] `writeException`
  (`src/lib/exceptionWriter.ts:41-45`) throws unless `input.category` is in
  `VALID_CATEGORIES = ['amount_mismatch', 'not_posted']`, a closed 2-value union type at
  the TypeScript level too (`ExceptionCategory`). This module is confirmed (per
  `MODULE_CONTRACTS.md`'s Callers field) to be the sole write path into `recon_exception`,
  called only by M-025 — no other code can insert a free-text category.
- **Enforcement point:** `src/lib/exceptionWriter.ts:41-45` (`writeException`)
- **Owning module:** M-020
- **Enforcing modules:** M-020 only (sole `recon_exception` write path; M-025 is the sole
  caller but sources its category value from M-020's own `ExceptionCategory` type, not an
  independent enforcement site)
- **Source:** `INVARIANTS.md` Scope = exception schema / matching / exception-handling
  tasks. Cross-reference: `VERIFICATION_CHECKLIST.md` records Automated/PASS via Task 5.4's
  `test_exception_schema_wiring.sh` and `exceptions.spec.ts`'s dedicated "no
  possible_duplicate_correction category ever appears" test.

- **ID:** S6
- **Statement:** If normalization rules change, historical matching can still identify
  which normalization version produced a given `silver.statement_line` row.
- **Category:** Operational
- **Scope:** TASK-SCOPED
- **Currently enforced:** YES — [STAGE-2-CONFIRMED — 2026-09-02] `NORMALIZATION_VERSION =
  'v1'` (`silverNormalization.ts:18`) is written into every `silver_statement_line` row's
  `normalization_version` column at insert time (`silverNormalization.ts:70,86`). No
  `UPDATE` against `silver_statement_line` exists anywhere in `src/` (confirmed via
  codebase-wide grep) — historical rows keep whatever version tagged them at write time,
  by the same INSERT-only architecture as G1/S11.
- **Enforcement point:** `src/lib/silverNormalization.ts:18,68-71,86`
  (`NORMALIZATION_VERSION` constant + `normalizeToSilver`'s INSERT)
- **Owning module:** M-024
- **Enforcing modules:** M-024 (sole writer of `silver_statement_line`, confirmed via
  `MODULE_CONTRACTS.md`'s Callers field — only M-022 calls it)
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
- **Enforcement point:** `src/lib/extractionPipeline.ts:23,81` (`MAX_ATTEMPTS = 2` and the
  `while (attemptNo < MAX_ATTEMPTS)` loop guard in `runExtractionPipeline`) —
  [STAGE-2-DIVERGENCE — 2026-09-02]: the entry's prior "Enforcement point"
  (`documentStatus.ts:139-165`, M-012) was the site of the *display-badge* false-positive
  fix, not the site that actually enforces the 2-attempt numeric bound. `documentStatus.ts`
  only reads existing attempt history to compute a label; it contains no logic that could
  ever block or permit a 3rd attempt. The real bound is `extractionPipeline.ts`'s own
  `MAX_ATTEMPTS` loop condition, confirmed by direct read (`extractionPipeline.ts:23,81,161-
  167`: once `attemptNo >= MAX_ATTEMPTS`, the function returns without looping again, and no
  external caller can re-enter `runExtractionPipeline` beyond that point either — see
  Enforcing modules below). Resolution required before Stage 3: the catalogue's Enforcement
  point attribution is corrected here to M-022; M-012 is retained below only as a secondary/
  incidental factor, not the primary enforcement site.
- **Owning module:** M-022
- **Enforcing modules:** M-022 (primary — the numeric bound itself), M-015 (secondary/
  incidental — `extraction.ts`'s G5 lock never releases `extracted_document.status` back
  from `'processing'` once set, per its own Known Fragility; in practice this also blocks
  any 3rd trigger attempt via `triggerExtraction`'s `WHERE status != 'processing'` guard,
  though this is a side effect of G5's lock design, not a deliberate S7 mechanism), M-012
  (display only — computes the badge reflecting attempt history; enforces nothing)
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
- **Currently enforced:** YES — [STAGE-2-CONFIRMED — 2026-09-02] `matchStatementLine`
  (`deterministicMatching.ts:153-214`) captures `_run_id`/`_extracted_at`/`_source_system`
  onto every outcome's `reference` field — for a resolved match (`ref` found), for an
  amount-mismatch (`ref` found but out of tolerance), and even for a `NOT_POSTED` miss
  (falls back to `findLatestReferenceWatermark()`, the reference table's own
  most-recently-extracted row, so "what state of NetSuite was checked" is still captured
  when nothing matched). `writeMatch` (`deterministicMatching.ts:220-227`) requires
  `reference` as a non-optional parameter, and its own doc comment confirms all 3 reference
  columns are `NOT NULL` at the schema level. `writeException`
  (`exceptionWriter.ts:41-61`) persists the same 3 columns when `reference` is non-null.
- **Enforcement point:** `src/lib/deterministicMatching.ts:153-214,220-227`
  (`matchStatementLine`, `writeMatch`)
- **Owning module:** M-026
- **Enforcing modules:** M-026 (captures + requires reference for every Match), M-020
  (`exceptionWriter.ts` — persists reference when present for an Exception), M-025
  (`matchingPipeline.ts` — passes `outcome.reference` through to both write paths
  unmodified)
- **Source:** `INVARIANTS.md` Scope = matching service task. Cross-reference:
  `VERIFICATION_CHECKLIST.md` records Automated/PASS via Task 5.2's
  `test_deterministic_matching.sh`.

- **ID:** S10
- **Statement:** Every extraction attempt is written to the `extracted` schema before
  validation occurs, never the reverse (reworded 2026-08-27, was "Bronze write precedes
  validation").
- **Category:** Operational
- **Scope:** TASK-SCOPED
- **Currently enforced:** YES — [STAGE-2-CONFIRMED — 2026-09-02] The write at
  `extractionPipeline.ts:118-132` happens unconditionally, before the retry/success
  decision at lines 145-168 — including on a caught catastrophic failure (subprocess spawn
  error, missing file: the `try/catch` at lines 96-116 degrades to a descriptive
  `rawOutput` string rather than skipping the write). The comment at lines 84-87 explicitly
  ties this ordering to S10/G1.
- **Enforcement point:** `src/lib/extractionPipeline.ts:96-132` (the try/catch around the
  extraction call, followed unconditionally by the attempt INSERT)
- **Owning module:** M-022
- **Enforcing modules:** M-022 (same enforcement point/module as G1 — S10 and G1 are two
  statements of the same underlying write-ordering guarantee)
- **Source:** `INVARIANTS.md` Scope = extraction service task. Cross-reference:
  `VERIFICATION_CHECKLIST.md` records Automated/PASS (covered within Task 3.1's clean
  script run).

- **ID:** S11
- **Statement:** Once a StatementLine's amount is extracted and written to Silver, it is
  immutable — never updated in place without a new version.
- **Category:** Data Correctness
- **Scope:** TASK-SCOPED
- **Currently enforced:** YES (by confirmed architectural absence, still not behaviorally
  exercised) — [STAGE-2-CONFIRMED — 2026-09-02] A codebase-wide grep for `UPDATE` against
  `silver_statement_line` returned zero hits — `normalizeToSilver`
  (`silverNormalization.ts:64-94`) only ever `INSERT`s, one row per extracted line, and no
  other module in the roster writes to this table (confirmed via `MODULE_CONTRACTS.md`'s
  Callers field — M-024 is the sole writer). This upgrades Stage 1's "holds by
  architectural absence, not behaviorally exercised" from an assumption to a confirmed grep
  result — the behavioral-exercise gap itself (no dedicated test) remains exactly as
  `VERIFICATION_CHECKLIST.md` recorded it; source reading cannot substitute for that.
- **Enforcement point:** `src/lib/silverNormalization.ts:64-94` (`normalizeToSilver` —
  INSERT-only; absence of any UPDATE code path elsewhere in `src/`)
- **Owning module:** M-024
- **Enforcing modules:** M-024 only
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
- **Currently enforced:** PARTIAL — [STAGE-2-UPDATE — 2026-09-02] Unlike the other 15
  entries, Stage 1 made no enforcement claim to confirm/deny here (it was explicitly
  flagged TBD); Stage 2 reading now finds the described mechanism DOES exist and IS wired
  in: `isDuplicateLine` (`silverNormalization.ts:38-49`) checks whether
  `vendor_id + normalized_invoice_ref + amount` already exists in `silver_statement_line`
  across ANY document for that vendor, and `normalizeToSilver` (line 78) sets
  `is_duplicate_line` accordingly on every insert. This is PARTIAL, not YES, because it is
  detection-only by explicit design (per the module's own Task 8.5 comment,
  `silverNormalization.ts:58-63`) — a duplicate line is flagged but still written and still
  reaches matching identically to any other row; no write is ever blocked or diverted. Since
  S12's own statement was never finalized (still "TBD" per `EXECUTION_PLAN.md` Task 8.5),
  whether PARTIAL is sufficient or a gap depends entirely on which of "detect" vs. "prevent"
  the eventual formal statement requires — an engineer decision, not something source
  reading can resolve on its own.
- **Enforcement point:** `src/lib/silverNormalization.ts:38-49,78` (`isDuplicateLine`,
  flag-only — "this is the gap" only insofar as prevention, not detection, is unenforced)
- **Owning module:** M-024
- **Enforcing modules:** M-024 only
- **Source:** `EXECUTION_PLAN.md` Task 8.5. Cross-reference: `VERIFICATION_CHECKLIST.md`
  records this task's verification script was never committed, and even the manual check
  that was attempted was incomplete (no real duplicate line existed in any tested
  document). Listed here as an open engineer decision, not a confirmed invariant — flagged
  for the Stage 3 Annotation Checklist as an OPEN_QUESTION, not a contradiction.

---

## New Implicit Invariant Candidates (Session D, Part 2)

Produced by walking every data-mutation touchpoint in `MODULE_CONTRACTS.md` (every module
with a real "Outputs" that writes to a table) against the 16 entries above. Two candidates
suggested by the session brief were considered and deliberately NOT elevated — reasoning
below, before the 3 that were.

**Considered and not elevated: exception-write idempotency (B10/M-020's flagged gap).**
`exceptionWriter.ts`'s own Known Fragility says "no idempotency guard... a caller retry
could double-insert." Read in isolation this looks like a candidate. But M-020 has exactly
one caller (M-025's `matchingPipeline.ts`), and that caller's own design closes the gap two
different ways: (1) `getEligibleLinesForDocument` (`matchingPipeline.ts:39-56`) re-selects
lines with `NOT EXISTS` a `recon_match`/`recon_exception` row EVERY time `runMatchingForDocument`
is invoked — a document that already has an exception for a line is never handed that line
again; and (2) every write for a document's matching run is buffered and committed in ONE
`db.transaction` (`matchingPipeline.ts:94-101`) — a mid-run throw rolls back the whole
batch, so a caller-level retry re-runs against the same NOT-EXISTS-filtered eligible set,
not a half-written one. Combined with G5's lock (a concurrent second `runMatchingForDocument`
for the same document can't even start), the realistic double-insert scenario the Known
Fragility describes does not appear reachable through this codebase's one real call path
today. Kept as a documented fragility (already captured in B10), not promoted to a new
catalogued invariant — it would become one immediately if a second caller of
`writeException` were ever added without equivalent guards.

---

**IC-CANDIDATE-01 — A processing-ownership lock (G5) must be recoverable after an unhandled failure; no work item may be left permanently stuck with no path back to eligibility**
Category: Operational
Scope: GLOBAL
Currently enforced: PARTIAL — YES for matching, NO for extraction
Enforcement point: `src/lib/matchingInvocation.ts:39,48-58` (`LOCK_STALE_AFTER_MINUTES` +
`acquireMatchingLock`'s `WHERE acquired_at < staleness-window` reclaim) enforces this for
matching. No equivalent exists for extraction — `src/lib/extraction.ts:36-49` sets
`status='processing'` and never resets it on any failure path; `runExtractionPipeline`
itself (`extractionPipeline.ts`) has no `finally`/rollback around the pipeline call at its
own call site either. **This is the gap** for the extraction side.
Owning module: M-017
Enforcing modules: M-017 only (matching side). None on the extraction side (M-015, M-046).
Rationale: G5 itself only requires that two owners can never process the same item
concurrently — both lock implementations satisfy that. This is a distinct, narrower
property G5 doesn't speak to: that a lock must not become a permanent dead end after a
crash. An unhandled exception mid-extraction (subprocess crash, unexpected DB error) leaves
`extracted_document.status='processing'` forever; `triggerExtraction`'s own G5 guard
(`WHERE status != 'processing'`) then permanently rejects every future Extract attempt for
that document, with no code path in this repository that ever resets it back — only direct
DB intervention recovers it. The matching lock, built later (Task 5.1) with a TTL-staleness
reclaim, does not have this failure mode. There is no principled reason evident in source
for the asymmetry — it reads as an implementation gap in the earlier (extraction) lock, not
a deliberate design difference.
Evidence: M-015's own Known Fragility ("No rollback of the 'processing' status column if
the pipeline throws — a document could get permanently stuck"); M-046's own Known Fragility
("Lock is non-releasing on failure... no finally/unlock path"); contrasted directly against
`matchingInvocation.ts:39,48-58`'s self-releasing, TTL-reclaimable design; confirmed via
direct read of `extraction.ts` (no `try/finally` around `runExtractionPipeline`) and
`MODULE_CONTRACTS.md`'s own "Cross-cutting findings" note on the two G5 implementations'
inconsistent recovery semantics.

**IC-CANDIDATE-02 — Array order in a static registry/constant must never be the sole signal for a production routing or default-assignment decision without an explicit, named marker**
Category: Data Correctness
Scope: TASK-SCOPED (vendor-extractor routing; Upload's legal-entity assignment)
Currently enforced: NO
Enforcement point: none — this is the gap, in two independent places.
Owning module: none (a cross-cutting gap, not one module's responsibility)
Enforcing modules: none
Rationale: Two unrelated pieces of routing/default logic both currently rely on array
position with no explicit marker, and both are silently reorder-fragile: (1)
`findKnownVendorExtractor` (`knownVendorExtractors.ts:46-48`) uses `Array.prototype.find`
over `KNOWN_VENDOR_EXTRACTORS`, so if two vendors' signature strings ever both appear as
substrings of the same document's text (plausible for short/generic signature strings as
more vendors are added), the FIRST array entry silently wins — mis-routing a real statement
to the wrong vendor's parser, corrupting extraction (a G2-adjacent risk) with no error or
log. (2) `UploadForm.tsx`'s `DEFAULT_LEGAL_ENTITY_ID = LEGAL_ENTITIES[0].id`
(`UploadForm.tsx:29`) is now the ONLY legal entity every uploaded document is attributed to
— legal entity is no longer user-selected at all ("engineer-directed simplification,
2026-08-30," per M-070's own Module Contract) — so reordering the static
`LEGAL_ENTITIES` array in `legalEntities.ts` silently reassigns every subsequent upload to
a different legal entity, with no test, type, or runtime guard that would catch it. Neither
site has an explicit `isDefault`/priority marker; both derive meaning purely from position
in a plain array. This is worth naming as one general implicit invariant (not two unrelated
ones) because it's the same underlying gap — "ordering carries unstated business meaning" —
appearing independently in two different layers of the same codebase.
Evidence: `MODULE_CONTRACTS.md`'s M-031 row ("Signature matching is a naive substring check
with array-order as an implicit tiebreak") and M-042 row ("since the default is
`LEGAL_ENTITIES[0]`, reordering the array silently changes Upload's default entity");
confirmed directly via `knownVendorExtractors.ts:46-48` and
`UploadForm.tsx:5,29` + `U23_UploadForm.md`'s Known Fragility ("The fixed
`DEFAULT_LEGAL_ENTITY_ID = LEGAL_ENTITIES[0].id` means array-order changes to
`LEGAL_ENTITIES` silently change which entity every new upload is assigned to").

**IC-CANDIDATE-03 — Every route must be reachable by its actual caller type; a machine-to-machine integration endpoint must not require end-user session authentication it cannot obtain**
Category: Security
Scope: TASK-SCOPED (`/api/matching/run-batch`, IP-005/n8n integration)
Currently enforced: NO
Enforcement point: none — this is the gap.
Owning module: M-043
Enforcing modules: none (no compensating auth — API key, shared secret, service token —
exists anywhere for this route)
Rationale: `proxy.ts`'s auth matcher (`src/proxy.ts:34-47`) excludes only `/login`,
`/api/health`, and static assets — confirmed by direct read of the matcher regex on line
45. `/api/matching/run-batch` (M-053) is NOT excluded, so every request to it must carry a
valid session cookie or `proxy.ts` redirects it to `/login` before the route handler ever
runs. But M-053 is documented (per `A02_module_call_map.md`'s Async Boundaries section and
`ID_REGISTRY.md`) as the receiving endpoint for an EXTERNAL scheduler (n8n, IP-005) calling
in from outside the codebase — with no browser, no user, and therefore no way to obtain or
present a session cookie the way `/api/documents` or `/api/exceptions` clients can. As
written, this means the scheduled-batch matching path — this build's only non-manual
matching trigger — is unreachable by its documented caller unless something entirely
outside this codebase (a shared secret injected out-of-band, a pre-authenticated service
session) compensates, none of which is visible in source. `/api/health` (M-051) shows the
pattern this route needed and didn't get: deliberately excluded from the matcher because
its caller (a health-check probe) can't authenticate either.
Evidence: `MODULE_CONTRACTS.md`'s M-053 row ("inherits M-043's session-cookie auth
requirement — unusual for a machine-to-machine trigger, since it isn't excluded from the
auth matcher the way M-051 is"); `U11_matching_run_batch_route.md`'s `[NOTABLE]` tag making
the same point at greater length; confirmed directly against `src/proxy.ts:34-47`'s matcher
regex, which lists only `login|api/health|_next/static|_next/image|...(static extensions)`
as exclusions — `matching/run-batch` matches none of them.
