STAGE-1-DRAFT: DOCS-DERIVED — 2026-09-01 — Produced by BCE Adapter Pipeline Stage 1

# INTAKE_SUMMARY.md — VIVE Statement Reconciliation

**Date:** 2026-09-01
**Engineer:** Vaishali
**Path:** C — PBVI Adapter (system was built under PBVI governance; all governing documents
present in `docs/`)
**Canonical layer boundary:** `extracted` schema (VIVE-specific intake — documents,
extraction attempts, per-vendor raw statement tables) is the canonical intake boundary,
kept separate from `bronze`/`silver`/`gold` (existing live NetSuite/CCC data). `silver.statement_line`
is the one shared, vendor-agnostic boundary where VIVE and NetSuite data coexist by design
(`ARCHITECTURE.md` D-J, §8).
**Session F disposition:** FULL EXTRACTION expected at Stage 2 — this is a real, running
application with committed source (`src/`, `scripts/`, `migrations/`), not a docs-only or
stub system.

**Stage 1 Human Gate:** Reviewed and confirmed — Engineer: Vaishali, Date: 2026-09-01.
"Proceed everything looks good." Stage 2 (source-code extraction) authorized to begin.

---

## System Purpose

Reconciles VIVE's vendor AP statement PDFs against NetSuite (AP bills) and CCC ONE
(repair-order data) on Microsoft Fabric: sign-in, statement upload, AI-assisted extraction
(deterministic-first for known vendors, Claude-primary otherwise), deterministic-first
matching with a narrowly-scoped AI-assisted residual pass that never auto-approves, a
vendor-grouped exception view with a lightweight resolution workflow, and simple
per-statement reporting via the existing Gold layer. Explicitly *not* solved by this build:
a formal human review/approval workspace (no segregation of duties, no dollar-threshold
second approval, no immutable audit ledger, no reversible bulk actions), formal
Reconciliation Runs, NetSuite write-back, or management reporting — all deferred to BCE.
(Source: `ARCHITECTURE.md` §1 Problem Framing, `docs/Claude.md` §1 System Intent.)

## Known Architecture

- **D-A** — Slice boundary: sign-in → upload → extract → match → vendor-grouped exceptions
  (with a lightweight resolution action, added 2026-09-01) → simple report.
- **D-B** — Adopts v3.3's data-pipeline decisions as-is (D7, D9, D17, document-level
  `legal_entity_id`), except D9 later amended (see below).
- **D-C** — Defers to BCE: formal Run object (D18–D20), optimistic locking (D12),
  NetSuite write-back (D10), full Gold/Power BI dashboards (D11).
- **D-D** — Reporting reads from the existing v3.3 Gold layer directly, not `recon`.
- **D-E** — Single user role, no in-application role differentiation.
- **D-F** — `legal_entity_id` at document level; entity-scoped *access* deferred (genuinely
  open, per D-F/OD5) — resolved 2026-09-01 by removing the Legal Entity picker from Upload
  (auto-assigned a single fixed default), not by building access scoping.
- **D-H** (amended 2026-08-26) — same vendor/period collisions are auto-resolved via
  version-chaining, no human checkpoint.
- **D-I** (amended 2026-09-01) — upload auto-triggers extraction (reversing the original
  "separate explicit acts" decision).
- **D-J** — VIVE intake data lives in a new `extracted` schema (documents, extraction
  attempts, per-vendor raw statement tables `extracted.stmt_<vendor_slug>`), separate from
  `bronze`/`silver`/`gold` (live NetSuite/CCC data). `silver.statement_line` is the shared
  normalization target.
- **D-K** — `extracted.document.artifact_type` column + a structured pipeline result
  contract (stage/status/candidate_ids/reason_codes/evidence/confidence/requires_review)
  used by every pipeline stage.
- **D-L** — known-vendor deterministic extraction fast path (pdfplumber-based, no LLM
  call), explicitly superseding the original requirements brief's universal-extraction-only
  scope (PHASE4_GATE_RECORD.md Finding 6) — 9 real vendors wired as of Session 9.
- **D-M** — reference-data reproducibility satisfied by capturing `_run_id`/`_extracted_at`/
  `_source_system` off the specific rows matched against, at match time (not a built
  snapshot mechanism) — NetSuite/CCC ingestion confirmed externally owned (amended
  2026-08-28), removing this build's originally-planned Session 4.
- **D-G** — Exception schema forward-compatibility: nullable `owner`/`aging_started_at`/
  `run_reference` columns exist now, unused, for BCE to activate later.

**Fixed stack** (`docs/Claude.md` §4): Azure App Service; Microsoft Fabric (Lakehouse
`bronze`, Warehouse `silver`/`gold`, SQL database `recon`), local SQLite fallback when
`FABRIC_SQL_ENDPOINT` is unset; dbt (`dbt-fabric` adapter); Claude Sonnet 5 via Azure AI
Foundry (primary, non-known-vendor documents) + deterministic pdfplumber extractors
(known-vendor bypass) + pdfplumber-based OCR fallback (built but inert — Tesseract/Poppler
not installed; Session 9 found OCR unnecessary for all 6 tested scanned vendors);
username/password auth (Entra ID is the stated end-goal, not built); n8n (monthly Run
Creation trigger + completion notifications only — does not orchestrate extraction/matching
itself); Playwright for UI testing.

## Known Pain Points

From `docs/ARCHITECTURE.md` §4 Key Risks (still-open items only — 2 of 4 already RESOLVED):
1. Version-chaining (D-H) has no human checkpoint — a genuinely conflicting (not
   corrective) statement for the same vendor/period silently supersedes the prior one with
   no flag raised. Sharper risk than before the 2026-08-26 amendment.
2. Access-scoping deferral (D-F) could surface a real architectural need later if entity-
   partitioned access turns out to be required, not just a screen filter.

From `docs/PHASE4_GATE_RECORD.md` Section D — one finding accepted, not resolved (ACCEPT
disposition): N2 ("never call NetSuite/CCC live from matching") has no enforcing invariant
since the original GLOBAL invariant was removed 2026-08-17. Remains true by construction
(no live-API code path exists), accepted as a documented convention, not a tested
invariant — revisit if a future task introduces a live-pull matching mode.

Additional pain point surfaced by this project's own Phase 8 Part 1 verification run
(2026-09-01, not from PHASE4_GATE_RECORD.md, but directly relevant): at least three fixture
scripts (`test_extraction_attempt_recording.mjs`, `test_bounded_retry.mjs`,
`test_foundation_schema.mjs`) are not safe to re-run against an already-used local SQLite
file — they seed a fixed vendor slug with no cleanup, causing spurious `UNIQUE constraint`
failures on a second run. See `verification/VERIFICATION_CHECKLIST.md`'s
Verification-Tooling Finding.

## Documents Reviewed

| Document | Contribution |
|---|---|
| `docs/ARCHITECTURE.md` (v1.6) | System purpose, key design decisions (D-A–D-M), key risks, open questions, data model |
| `docs/INVARIANTS.md` (v1.7) | G1–G5 (Global), S1–S11 (task-scoped), T1–T7 (deferred/BCE-scope) invariant registry |
| `docs/EXECUTION_PLAN.md` (v1.8) | Session/task structure, verification commands, regression classifications, invariant-enforcement mapping per task |
| `docs/Claude.md` (v1.3) | System intent summary, fixed stack, scope boundary |
| `PROJECT_MANIFEST.md` | File registry, phase status, known prior-art note |
| `verification/VERIFICATION_CHECKLIST.md` | Phase 8 Part 1 sign-off — session completion, invariant validation results (one real FAIL: S7 status-badge display bug), architecture alignment, operational readiness |
| `docs/PHASE4_GATE_RECORD.md` | Design Gate evaluation criteria, requirements traceability, adversarial stress-test findings, risk register with dispositions |

## Open Questions Before Extraction

From `docs/ARCHITECTURE.md` §6 (only the genuinely-still-open item; the other four are
marked RESOLVED/PARTIALLY RESOLVED in the source and are not re-listed here as open):
1. Real per-user authentication/identity is required for OD5's multiple-named-users
   confirmation; entity-scoped access (D-F) remains open pending a UI Discovery finding
   that never materialized in this bounded build.

From `docs/INVARIANTS.md` v1.7's own new item: OD6 — whether the exception-resolution
workflow (status/note/resolved_at columns, added 2026-09-01) warrants a named invariant, or
stays an unenforced implementation detail. Unresolved as of this revision.

From this Stage 1 pass itself (new, not previously tracked in any doc): Task 8.5's own
"Invariant enforcement: TBD" note (row-level duplicate detection) — engineer has not yet
decided whether this warrants a new task-scoped invariant (candidate S12).

## Confidence Assessment

**HIGH** — PBVI artifacts are structured and high-fidelity. This project additionally has
an unusually deep changelog/amendment trail (every ARCHITECTURE.md/INVARIANTS.md/
EXECUTION_PLAN.md decision is dated and attributed), and a Phase 8 Part 1 verification pass
completed 2026-09-01 with real, run-confirmed results rather than documentation claims
alone — raising confidence above a typical docs-only intake.
