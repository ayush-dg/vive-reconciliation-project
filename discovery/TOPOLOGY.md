STAGE-1-DRAFT: DOCS-DERIVED — 2026-09-01 — Produced by BCE Adapter Pipeline Stage 1

# TOPOLOGY.md — VIVE Statement Reconciliation

Source: `docs/ARCHITECTURE.md` §8 (Data Model), `docs/Claude.md` §4 (Fixed Stack),
`docs/EXECUTION_PLAN.md` (session/task structure). No source code read at this stage —
every "Handoff mechanism" and "Auth"/"Error handling" field below is either stated
explicitly in docs or marked NOT DETERMINABLE FROM SOURCE, never inferred from module
naming or convention.

---

## A01 — Layer Boundary Map

- Produced by: Upload UI (client-side form submit)
- Artifact: multipart PDF file + `legal_entity_id`
- Consumed by: Document registration endpoint
- Handoff mechanism: direct call (HTTP API)
- Failure mode: NOT DETERMINABLE FROM SOURCE

- Produced by: Document registration endpoint (Task 2.2)
- Artifact: `extracted.document` row (content-hash deduped, `artifact_type` per D-K)
- Consumed by: Extract trigger / extraction service
- Handoff mechanism: database write, then read (same `extracted` schema)
- Failure mode: NOT DETERMINABLE FROM SOURCE

- Produced by: Extract action endpoint (Task 2.4) — auto-triggered on upload as of D-I
  (amended 2026-09-01), previously a separate explicit click
- Artifact: extraction invocation, with G5 processing-ownership acquisition (per
  `ARCHITECTURE.md` D-A gate)
- Consumed by: Extraction service — vendor identification and routing (Task 3.1)
- Handoff mechanism: direct call
- Failure mode: NOT DETERMINABLE FROM SOURCE

- Produced by: Extraction service (deterministic pdfplumber path for known vendors, or
  Claude-primary path for others — routing per Task 3.1)
- Artifact: `extracted.extraction_attempt` row (append-only, G1) + one
  `extracted.stmt_<vendor_slug>` raw row per line (per-vendor native column shape, D-J)
- Consumed by: Validation gate (Task 3.2)
- Handoff mechanism: database write, then read
- Failure mode: NOT DETERMINABLE FROM SOURCE

- Produced by: Validation gate (structural + arithmetic check, G2)
- Artifact: pass/fail gate result (confidence carried as diagnostic metadata only, not a
  gate input)
- Consumed by: Silver normalization (Task 3.6) on PASS; retry/exception path on FAIL
  (bounded to 2 attempts, S7)
- Handoff mechanism: direct call (gated write)
- Failure mode: NOT DETERMINABLE FROM SOURCE

- Produced by: Silver normalization (Task 3.6) — transforms `extracted.stmt_*` raw rows
  into the shared vendor-agnostic shape
- Artifact: `silver.statement_line` row (normalization-version-tagged, S6)
- Consumed by: Matching service (Task 5.1/5.2/5.3)
- Handoff mechanism: database write, then read (shared table — VIVE and NetSuite-derived
  Silver data coexist here by design)
- Failure mode: NOT DETERMINABLE FROM SOURCE

- Produced by: Matching service — deterministic-first (Task 5.2), narrow AI-assisted
  residual pass that never auto-approves (Task 5.3, G3 + AI-write-authority non-negotiable)
- Artifact: `recon.match` / `recon.exception` row, via the D-K structured pipeline result
  contract (stage/status/candidate_ids/reason_codes/evidence/confidence/requires_review);
  reference-data reproducibility captured at match time (`_run_id`/`_extracted_at`/
  `_source_system`, D-M) since no Silver snapshot mechanism is built
- Consumed by: Home screen (summary stats), Exceptions screen (vendor-grouped list +
  resolution workflow)
- Handoff mechanism: database write, then read via API endpoints
- Failure mode: NOT DETERMINABLE FROM SOURCE

- Produced by: existing v3.3 Gold layer (dbt-transformed, materialized Fabric Warehouse
  tables — external to and reused as-is by this build, per D-D)
- Artifact: `ReportView` (Gold, per-statement/per-cycle results)
- Consumed by: **no active consuming task in this build** — Session 7 (Gold reporting
  integration) was removed from `EXECUTION_PLAN.md` by engineer direction (2026-08-28/
  2026-09-01); Home's current summary stats (Task 6.1) read `recon`/`extracted` directly
  instead, a known, deliberate interim state per prior-session memory, not this crossing
- Handoff mechanism: NOT DETERMINABLE FROM SOURCE (no implementing task exists to confirm)
- Failure mode: NOT DETERMINABLE FROM SOURCE

---

## A02 — Module Call Map

DEFERRED: Module Call Map requires source code inspection. Produced in Stage 2.

---

## A03 — External System Boundary Map

- System: Claude (Anthropic) via Azure AI Foundry
- Direction: outbound
- Protocol/mechanism: API call (model: Claude Sonnet 5 — corrected 2026-09-01 from an
  originally-named 4.6, a documented Scope Decision)
- Purpose: primary extraction path for non-known-vendor documents; narrow AI-assisted
  residual matching pass (never auto-approves, G3-gated — vendor/document content treated
  strictly as input data, never concatenated into model instructions)
- Auth: NOT DETERMINABLE FROM SOURCE
- Error handling: NOT DETERMINABLE FROM SOURCE (bounded retry exists at the extraction
  service level per S7 — max 2 attempts, then `OCR_LOW_CONFIDENCE` — but whether that
  retry logic itself distinguishes API-call failure modes is not stated in docs)

- System: Microsoft Fabric — SQL database (`recon`)
- Direction: outbound (read/write)
- Protocol/mechanism: connects via `FABRIC_SQL_ENDPOINT` env var; falls back to local
  SQLite when unset
- Purpose: primary transactional store for this build's own data (matches, exceptions)
- Auth: NOT DETERMINABLE FROM SOURCE
- Error handling: NOT DETERMINABLE FROM SOURCE

- System: Microsoft Fabric — Lakehouse (`bronze`)
- Direction: inbound (read-only from this build's perspective)
- Protocol/mechanism: NOT DETERMINABLE FROM SOURCE (docs state the schema exists and is
  externally populated, not the connection mechanism this build uses to read it)
- Purpose: existing live NetSuite/CCC reference data, externally owned and ingested by a
  separate Fabric pipeline (confirmed 2026-08-28, not built by this project)
- Auth: NOT DETERMINABLE FROM SOURCE
- Error handling: NOT DETERMINABLE FROM SOURCE

- System: Microsoft Fabric — Warehouse (`silver`, `gold`)
- Direction: outbound (write to `silver.statement_line`), inbound (read from `gold` for
  reporting, currently unimplemented — see A01)
- Protocol/mechanism: dbt, `dbt-fabric` adapter, writing directly to Fabric Warehouse
- Purpose: shared normalization layer (`silver`) and existing reused Gold reporting layer
- Auth: NOT DETERMINABLE FROM SOURCE
- Error handling: NOT DETERMINABLE FROM SOURCE

- System: n8n
- Direction: inbound (triggers this build) / outbound (notifications)
- Protocol/mechanism: NOT DETERMINABLE FROM SOURCE (docs state its role, not the transport)
- Purpose: triggers the monthly Run Creation API call and sends completion notifications
  only — explicitly does not orchestrate extraction or matching itself
- Auth: NOT DETERMINABLE FROM SOURCE
- Error handling: NOT DETERMINABLE FROM SOURCE

- System: Entra ID / company SSO
- Direction: N/A — not integrated
- Protocol/mechanism: N/A
- Purpose: stated end-goal auth mechanism; this build's actual v1 mechanism is
  username/password. The Sign In screen's "Sign in with company SSO" button is a disabled
  placeholder (`UI_SURFACE.md` unresolved gap #1), not a working integration
- Auth: N/A (not built)
- Error handling: N/A (not built)

**Note:** Per BCE Stage 1 convention, IP-NNN IDs and "Called by" (M-NNN) cross-references
are not assigned at this stage — both require the Module Roster built in Stage 2 from
source code. This file's A03 records are ID-less until Stage 2 completes them.
