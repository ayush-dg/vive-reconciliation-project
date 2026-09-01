STAGE-1-DRAFT: DOCS-DERIVED — 2026-09-01 — Produced by BCE Adapter Pipeline Stage 1

# MODULE_CONTRACTS.md — VIVE Statement Reconciliation

T4 skeletons (Template 9's contract format), one per functional area identified from
`docs/ARCHITECTURE.md`'s design decisions and `docs/EXECUTION_PLAN.md`'s session/task
structure — not from a source-code module inventory, which does not exist until Stage 2's
Module Roster (A02). Labels use the `S1-[NN]_[module_name]` convention. Fields not fillable
from docs alone (Public Interface, Error Behaviour, Known Fragility, Change Impact) are
marked NOT DETERMINABLE FROM SOURCE at every entry, unconditionally, per Stage 1 rules —
not a per-module judgment call.

---

## S1-01_authentication

- **Module:** Authentication (Sign In, session management)
- **Layer:** Application / UI+API boundary
- **Primary Responsibility:** Username/password sign-in (v1 mechanism); session idle
  timeout redirect; Entra ID/SSO is the stated end-goal, rendered as a disabled placeholder
  only (`docs/Claude.md` §4, `UI_SURFACE.md` gap #1)
- **Inputs:** username/password credentials (Task 1.3)
- **Outputs:** authenticated session; redirect to `/login` on session expiry
- **External Dependencies:** NOT DETERMINABLE FROM SOURCE (session-store mechanism not
  stated in docs)
- **Internal Dependencies:** none stated
- **Public Interface:** NOT DETERMINABLE FROM SOURCE
- **Error Behaviour:** NOT DETERMINABLE FROM SOURCE
- **Known Fragility:** NOT DETERMINABLE FROM SOURCE
- **Change Impact:** NOT DETERMINABLE FROM SOURCE

## S1-02_document_intake

- **Module:** Document intake — Upload UI + registration + content-hash dedup
- **Layer:** Application / UI+API boundary → `extracted` schema write
- **Primary Responsibility:** Register an uploaded PDF as an `extracted.document` row;
  reject byte-identical re-uploads (G4); auto-trigger extraction on upload (D-I, amended
  2026-09-01)
- **Inputs:** multipart PDF file, `legal_entity_id` (auto-assigned single default as of
  2026-09-01 — Legal Entity picker removed, D-F resolution note)
- **Outputs:** `extracted.document` row (`artifact_type = vendor_statement` per D-K)
- **External Dependencies:** Fabric SQL database `recon`/`extracted` schema (or local
  SQLite fallback)
- **Internal Dependencies:** hands off to extraction service on successful registration
- **Public Interface:** NOT DETERMINABLE FROM SOURCE
- **Error Behaviour:** NOT DETERMINABLE FROM SOURCE
- **Known Fragility:** NOT DETERMINABLE FROM SOURCE
- **Change Impact:** NOT DETERMINABLE FROM SOURCE

## S1-03_extraction_service

- **Module:** Extraction service — vendor identification, routing, attempt recording
- **Layer:** Application / `extracted` schema write
- **Primary Responsibility:** Identify vendor during extraction (not user-selected at
  upload, per D-L amendment); route to deterministic pdfplumber path (known vendors, no LLM
  call) or Claude-primary path (Azure AI Foundry); record each attempt append-only (G1),
  bounded to 2 attempts (S7); enforce G5 processing-ownership acquisition
- **Inputs:** `extracted.document` row; PDF content
- **Outputs:** `extracted.extraction_attempt` row (raw output, confidence as diagnostic
  metadata only, provider used, attempt number); one `extracted.stmt_<vendor_slug>` raw row
  per line
- **External Dependencies:** Claude (Anthropic) via Azure AI Foundry (non-known-vendor
  path); pdfplumber-based OCR fallback (built but inert — Tesseract/Poppler not installed,
  found unnecessary for all 6 tested scanned vendors per Session 9 Task 9.6)
- **Internal Dependencies:** hands off to validation gate
- **Public Interface:** NOT DETERMINABLE FROM SOURCE
- **Error Behaviour:** NOT DETERMINABLE FROM SOURCE
- **Known Fragility:** `verification/VERIFICATION_CHECKLIST.md` (Phase 8 Part 1, 2026-09-01)
  records that this module's raw-row write previously threw uncaught (fixed commit
  `b2a691c`, `ensureKnownVendor()` never called `ensureVendorStmtTable()`) — the fix is
  committed, but this is prior documented fragility, not NOT DETERMINABLE
- **Change Impact:** NOT DETERMINABLE FROM SOURCE

## S1-04_validation_gate

- **Module:** Structural + arithmetic validation gate
- **Layer:** Application (gate between `extracted` and `silver`)
- **Primary Responsibility:** Enforce G2 — a document is match-eligible only after passing
  structural (invoice_number/ro_number present) and arithmetic validation; confidence is
  diagnostic metadata only, never a gate input (amended 2026-08-26, removing what
  INVARIANTS.md v1.2 called "the single highest-value control in the pipeline" — recorded
  as a deliberate, accepted trade)
- **Inputs:** `extracted.extraction_attempt` row
- **Outputs:** PASS → eligible for Silver normalization; FAIL → retry (bounded, S7) or
  exception
- **External Dependencies:** none stated
- **Internal Dependencies:** consumes extraction service output; gates Silver normalization
- **Public Interface:** NOT DETERMINABLE FROM SOURCE
- **Error Behaviour:** NOT DETERMINABLE FROM SOURCE
- **Known Fragility:** NOT DETERMINABLE FROM SOURCE
- **Change Impact:** NOT DETERMINABLE FROM SOURCE

## S1-05_silver_normalization

- **Module:** Silver normalization (`extracted.stmt_*` → `silver.statement_line`)
- **Layer:** `extracted` → `silver` schema transform
- **Primary Responsibility:** Normalize each vendor's native-shape raw rows into the single
  shared `silver.statement_line` shape; tag with normalization-version for traceability
  (S6); blank-amount (credit/payment) lines reach Silver rather than being pre-emptively
  diverted (2026-08-26 change)
- **Inputs:** `extracted.stmt_<vendor_slug>` raw rows, gated on G2 PASS
- **Outputs:** `silver.statement_line` rows
- **External Dependencies:** none stated
- **Internal Dependencies:** gated by validation gate; feeds matching service
- **Public Interface:** NOT DETERMINABLE FROM SOURCE
- **Error Behaviour:** NOT DETERMINABLE FROM SOURCE
- **Known Fragility:** NOT DETERMINABLE FROM SOURCE
- **Change Impact:** `docs/PHASE4_GATE_RECORD.md` Finding 1 (BLOCKER, RESOLVED) notes that
  without this module, matching reads from a table nothing writes to — i.e. this module's
  absence was once a system-breaking gap, now closed by Task 3.6

## S1-06_matching_service

- **Module:** Matching service — deterministic-first + AI-assisted residual
- **Layer:** `silver` → `recon` schema write
- **Primary Responsibility:** Deterministic SQL-based matching first (Task 5.2); narrow
  AI-assisted residual pass on remainder (Task 5.3) that never auto-approves — writes only
  a proposed field (G3 + the core AI-write-authority non-negotiable). Reference-data
  reproducibility captured at match time (`_run_id`/`_extracted_at`/`_source_system`, D-M),
  not via a built snapshot mechanism, since the external NetSuite/CCC pipeline's Lakehouse
  tables are upsert-in-place with no retained history
- **Inputs:** `silver.statement_line` rows; `bronze` reference data (externally owned)
- **Outputs:** `recon.match` / `recon.exception` rows via the D-K structured pipeline
  result contract
- **External Dependencies:** Claude (Anthropic) via Azure AI Foundry (residual pass only);
  Fabric Lakehouse `bronze` (read-only, externally populated)
- **Internal Dependencies:** consumes Silver normalization output; feeds Home/Exceptions UI
- **Public Interface:** NOT DETERMINABLE FROM SOURCE
- **Error Behaviour:** NOT DETERMINABLE FROM SOURCE
- **Known Fragility:** NOT DETERMINABLE FROM SOURCE
- **Change Impact:** NOT DETERMINABLE FROM SOURCE

## S1-07_exceptions_ui

- **Module:** Exceptions — vendor-grouped list + two-pane detail + resolution workflow
- **Layer:** UI+API boundary
- **Primary Responsibility:** Vendor-grouped two-pane master-detail view (rewritten
  2026-09-01, replacing a flat all-vendor list + separate detail page); lightweight
  resolution workflow (Mark resolved / Flag for vendor / Skip + optional note) — single-role,
  no undo, no per-action attribution beyond the row's own `status`/`note`/`resolved_at`
  columns (D-A amendment, still short of full BCE-scope review/approval)
- **Inputs:** `recon.exception` rows
- **Outputs:** updated exception `status`/`note`/`resolved_at`
- **External Dependencies:** none stated
- **Internal Dependencies:** consumes matching service output
- **Public Interface:** NOT DETERMINABLE FROM SOURCE
- **Error Behaviour:** NOT DETERMINABLE FROM SOURCE
- **Known Fragility:** NOT DETERMINABLE FROM SOURCE
- **Change Impact:** NOT DETERMINABLE FROM SOURCE

## S1-08_home_ui

- **Module:** Home dashboard
- **Layer:** UI+API boundary
- **Primary Responsibility:** Statement list, status badges, summary stats, Reconcile
  action. Currently reads `recon`/`extracted` directly via `getHomeSummaryStats()`, not the
  Gold `ReportView` — a known, deliberate interim state (Session 7/Gold integration
  removed, not yet built)
- **Inputs:** `extracted.document`, `recon.match`/`recon.exception` rows
- **Outputs:** summary stats display; Reconcile trigger to matching service
- **External Dependencies:** none stated
- **Internal Dependencies:** reads extraction + matching service output
- **Public Interface:** NOT DETERMINABLE FROM SOURCE
- **Error Behaviour:** NOT DETERMINABLE FROM SOURCE
- **Known Fragility:** `verification/VERIFICATION_CHECKLIST.md` (Phase 8 Part 1, 2026-09-01)
  records a real, currently-unfixed FAIL here (S7 invariant check): after a bounded-retry
  sequence's 2nd attempt succeeds, the status badge does not correctly read
  "Processing"/matching-eligible — underlying data is correct, only the displayed badge is
  wrong
- **Change Impact:** NOT DETERMINABLE FROM SOURCE

## S1-09_document_detail_ui

- **Module:** Document Detail screen
- **Layer:** UI+API boundary
- **Primary Responsibility:** Extracted rows + extraction-method summary (OCR/Claude/
  pdfplumber counts) for a single document
- **Inputs:** `extracted.extraction_attempt` rows (provider field, per Task 3.5's summary
  endpoint)
- **Outputs:** extraction-method summary display
- **External Dependencies:** none stated
- **Internal Dependencies:** reads extraction service output
- **Public Interface:** NOT DETERMINABLE FROM SOURCE
- **Error Behaviour:** NOT DETERMINABLE FROM SOURCE
- **Known Fragility:** NOT DETERMINABLE FROM SOURCE
- **Change Impact:** NOT DETERMINABLE FROM SOURCE

## S1-10_known_vendor_extractors

- **Module:** Per-vendor deterministic extractors (pdfplumber-based)
- **Layer:** Application, invoked from extraction service
- **Primary Responsibility:** Zero-LLM-call extraction for 9 real known vendors as of
  Session 9 (Keystone, Fred Beans, Wilbert's, Quirk, Adas, Empire, Astech, Precision, plus
  the original Lia bypass), each preserving its own documented reconciliation rule (which
  column is the correct line amount) — explicitly not generalized into one shared parser
- **Inputs:** vendor-identified PDF (via signature match in the known-vendor registry)
- **Outputs:** `extracted.stmt_<vendor_slug>` raw rows reconciling to the statement's own
  printed total within $0.01 (verified live for all 9, per
  `scripts/verify_known_vendor_extractors.mjs`, `verification/HARNESS.sh`)
- **External Dependencies:** none (explicitly no LLM call — the point of this module)
- **Internal Dependencies:** invoked by S1-03 extraction service on a known-vendor-registry
  match
- **Public Interface:** NOT DETERMINABLE FROM SOURCE
- **Error Behaviour:** NOT DETERMINABLE FROM SOURCE
- **Known Fragility:** Key Rotunda's vendor (a scanned/OCR-path vendor, not one of these 9
  deterministic ones) has a known, unfixed extraction gap — includes two
  payment/remittance-total rows as if they were transaction lines, an engineer-directed
  scope stop per Session 9 Task 9.6, not built into this module or any other
- **Change Impact:** NOT DETERMINABLE FROM SOURCE
