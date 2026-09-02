STAGE-1-DRAFT: DOCS-DERIVED — 2026-09-01 — Produced by BCE Adapter Pipeline Stage 1
STAGE-2-STATUS: A01 and A03 reconciled against source, A02 complete — 2026-09-02, BCE
Adapter Pipeline Stage 2 Session A. See inline [STAGE-2-UPDATE — ...] tags below for every
field Stage 2 confirmed or corrected. Zero [STAGE-2-DIVERGENCE] tags were needed — nothing
Stage 1 claimed was contradicted by source code, only elaborated or confirmed.

# TOPOLOGY.md — VIVE Statement Reconciliation

Source: `docs/ARCHITECTURE.md` §8 (Data Model), `docs/Claude.md` §4 (Fixed Stack),
`docs/EXECUTION_PLAN.md` (session/task structure). No source code read at this stage —
every "Handoff mechanism" and "Auth"/"Error handling" field below is either stated
explicitly in docs or marked NOT DETERMINABLE FROM SOURCE, never inferred from module
naming or convention. **(Stage 1 framing — see STAGE-2-STATUS above for what Stage 2 later
confirmed/added.)**

---

## A01 — Layer Boundary Map

- Produced by: Upload UI (client-side form submit) — M-070 (UploadForm.tsx)
- Artifact: multipart PDF file + `legal_entity_id`
- Consumed by: Document registration endpoint — M-044 (`api/documents/route.ts`)
- Handoff mechanism: direct call (HTTP `fetch` POST, confirmed — M-070:106)
- Failure mode: [STAGE-2-UPDATE — 2026-09-02]: M-044's POST handler validates MIME/
  extension/size/legal-entity before calling `registerDocument` (M-011); a duplicate
  content-hash is detected via `findDocumentByHash` and is not re-registered (G4) — this is
  a silent success path, not an error. Deeper exception-handling behavior beyond this was
  not traced in this pass — remainder NOT DETERMINABLE FROM SOURCE.

- Produced by: Document registration endpoint (Task 2.2) — M-011 (documents.ts)
- Artifact: `extracted.document` row (content-hash deduped, `artifact_type` per D-K)
- Consumed by: Extract trigger / extraction service — M-046 (`extract/route.ts`) → M-015
  (extraction.ts)
- Handoff mechanism: database write, then read (same `extracted` schema, confirmed — both
  go through M-003's `getSqliteDb()`/`getFabricPool()`)
- Failure mode: [STAGE-2-UPDATE — 2026-09-02]: M-046 returns 404 if the document doesn't
  exist, 409 if already processing (G5 lock, confirmed via M-015's atomic status flip).

- Produced by: Extract action endpoint (Task 2.4) — M-046 — auto-triggered on upload as of
  D-I (amended 2026-09-01), previously a separate explicit click
- Artifact: extraction invocation, with G5 processing-ownership acquisition (per
  `ARCHITECTURE.md` D-A gate)
- Consumed by: Extraction service — vendor identification and routing (Task 3.1) — M-021
  (vendorIdentification.ts)
- Handoff mechanism: direct call (confirmed — M-015:49 `await runExtractionPipeline`)
- Failure mode: [STAGE-2-UPDATE — 2026-09-02]: same 404/409 pattern as above at M-046; once
  inside M-022 (extractionPipeline.ts), failures are governed by bounded retry (S7, max 2
  attempts total), not surfaced immediately to the caller.

- Produced by: Extraction service (deterministic pdfplumber path for known vendors, or
  Claude-primary path for others — routing per Task 3.1) — M-021, dispatching to one of
  M-032–M-040 (deterministic) or M-028 (Claude) or M-030 (OCR fallback)
- Artifact: `extracted.extraction_attempt` row (append-only, G1) + one
  `extracted.stmt_<vendor_slug>` raw row per line (per-vendor native column shape, D-J)
- Consumed by: Validation gate (Task 3.2) — M-023 (validationGate.ts)
- Handoff mechanism: database write, then read
- Failure mode: [STAGE-2-UPDATE — 2026-09-02]: M-023 runs structural + arithmetic checks;
  FAIL routes back into M-022's bounded-retry loop (max 2 total attempts, S7) rather than
  raising an exception directly to the HTTP caller.

- Produced by: Validation gate (structural + arithmetic check, G2) — M-023
- Artifact: pass/fail gate result (confidence carried as diagnostic metadata only, not a
  gate input)
- Consumed by: Silver normalization (Task 3.6) on PASS — M-024 (silverNormalization.ts);
  retry/exception path on FAIL (bounded to 2 attempts, S7) — back into M-022
- Handoff mechanism: direct call (confirmed — M-022:147 `normalizeToSilver(...)`)
- Failure mode: [STAGE-2-UPDATE — 2026-09-02]: on PASS, M-022 calls M-024 synchronously;
  M-024 also flags (never gates) row-level duplicates per Task 8.5. Exception behavior
  inside M-024 beyond dedup-flagging was not traced in depth — remainder NOT DETERMINABLE
  FROM SOURCE.

- Produced by: Silver normalization (Task 3.6) — M-024 — transforms `extracted.stmt_*` raw
  rows into the shared vendor-agnostic shape
- Artifact: `silver.statement_line` row (normalization-version-tagged, S6)
- Consumed by: Matching service (Task 5.1/5.2/5.3) — M-017 (matchingInvocation.ts) → M-025
  (matchingPipeline.ts)
- Handoff mechanism: database write, then read (shared table — VIVE and NetSuite-derived
  Silver data coexist here by design)
- Failure mode: [STAGE-2-UPDATE — 2026-09-02]: matching is a separate, explicitly-triggered
  entry point (M-017/M-025 via M-047/M-053), never automatically chained from extraction —
  confirms the architectural pattern extends S1 (upload never triggers matching) to
  "extraction never triggers matching" either. M-047 returns the same 404/409 lock pattern
  as extraction.

- Produced by: Matching service — deterministic-first (Task 5.2, M-026) — narrow
  AI-assisted residual pass that never auto-approves (Task 5.3, M-027, G3 +
  AI-write-authority non-negotiable)
- Artifact: `recon.match` / `recon.exception` row, via the D-K structured pipeline result
  contract (stage/status/candidate_ids/reason_codes/evidence/confidence/requires_review);
  reference-data reproducibility captured at match time (`_run_id`/`_extracted_at`/
  `_source_system`, D-M) since no Silver snapshot mechanism is built
- Consumed by: Home screen (summary stats) — M-068 via M-044/M-052; Exceptions screen
  (vendor-grouped list + resolution workflow) — M-072/M-074 via M-048/M-049/M-050
- Handoff mechanism: database write, then read via API endpoints
- Failure mode: [STAGE-2-UPDATE — 2026-09-02]: UI-layer fetch failures render via the
  shared `InlineLoadError` component (M-081) — confirmed reused identically by
  M-068/M-072/M-074/M-076 (Task 6.4's own consistency test), not a per-screen bespoke error
  path.

- Produced by: existing v3.3 Gold layer (dbt-transformed, materialized Fabric Warehouse
  tables — external to and reused as-is by this build, per D-D)
- Artifact: `ReportView` (Gold, per-statement/per-cycle results)
- Consumed by: **no active consuming task in this build** — Session 7 (Gold reporting
  integration) was removed from `EXECUTION_PLAN.md` by engineer direction (2026-08-28/
  2026-09-01); Home's current summary stats (Task 6.1, M-014) read `recon`/`extracted`
  directly instead, a known, deliberate interim state per prior-session memory, not this
  crossing
- Handoff mechanism: [STAGE-2-UPDATE — 2026-09-02]: **confirmed, not just undetermined** —
  Session A0's full codebase map found zero Gold-layer/ReportView/dbt-invoking source files
  anywhere in this codebase. This crossing has no implementation at all, matching Stage 1's
  claim exactly; there is nothing further to determine, not merely something undetermined.
- Failure mode: N/A — no code exists for this crossing to fail.

---

## A02 — Module Call Map

**COMPLETE as of 2026-09-02 (BCE Stage 2 Session A).** Full Module Roster (78 modules,
M-001–M-054 backend + M-060–M-083 UI), Internal Call Table, Startup Sequence, and Async
Boundaries live in `discovery/components/A02_module_call_map.md` — not duplicated here to
avoid drift between two copies of the same data. Key findings: no internal
producer/consumer async boundaries exist anywhere in this codebase (no queue, no
background worker); migrations are not auto-applied at app startup (a manual operational
prerequisite, confirmed by `migrate.ts`/M-007 being unreachable from the request-serving
call graph); one dynamic-dispatch call site (M-021, known-vendor extractor selection) has
an uncertain single target among 9 possibilities at static-analysis time.

---

## A03 — External System Boundary Map

- **IP-001** — System: Claude (Anthropic) via Azure AI Foundry
- Direction: outbound
- Protocol/mechanism: API call (model: Claude Sonnet 5 — corrected 2026-09-01 from an
  originally-named 4.6, a documented Scope Decision)
- Purpose: primary extraction path for non-known-vendor documents; narrow AI-assisted
  residual matching pass (never auto-approves, G3-gated — vendor/document content treated
  strictly as input data, never concatenated into model instructions)
- Called by: M-028 (aiProvider.ts, the sole direct caller) — reached transitively from
  M-021 (vendorIdentification.ts) and M-027 (aiResidualMatching.ts)
- Auth: NOT DETERMINABLE FROM SOURCE
- Error handling: [STAGE-2-UPDATE — 2026-09-02]: M-028 falls back through three tiers —
  Azure AI Foundry, then direct Anthropic API, then a deterministic marker-text mock —
  depending on configured credentials and the `EXTRACTION_LIVE_TESTS` opt-in. Bounded
  retry (S7, max 2 attempts) governs failure at the extraction-service level above M-028;
  whether M-028 itself distinguishes API-call failure *types* (rate limit vs. auth vs.
  timeout) was not confirmed in this pass.

- **IP-002** — System: Microsoft Fabric — SQL database (`recon`)
- Direction: outbound (read/write)
- Protocol/mechanism: connects via `FABRIC_SQL_ENDPOINT` env var (`mssql` driver); falls
  back to local SQLite (`better-sqlite3`) when unset
- Purpose: primary transactional store for this build's own data (matches, exceptions)
- Called by: M-003 (db.ts, the sole direct caller — every other module reaches this
  through M-003, confirmed by Session A's call table)
- Auth: NOT DETERMINABLE FROM SOURCE — genuinely undetermined, not merely stale (no
  component file found a credential mechanism beyond the bare `FABRIC_SQL_ENDPOINT`
  connection string)
- Error handling: [STAGE-2-UPDATE — 2026-09-02, backported from Session E]: `getFabricPool()`
  throws explicitly if `FABRIC_SQL_ENDPOINT` is unset (no silent fallback at this layer).
  **Known bug (see `discovery/RISK_REGISTER.md` R-004):** a failed `.connect()` permanently
  caches the *rejected* promise in `db.ts`'s module-level singleton — every subsequent
  caller gets the same rejection with no automatic retry until `closeDb()` is explicitly
  invoked. Shares its one connection pool with IP-004's `silver` write path — a failure in
  one is simultaneously a failure in the other, despite being catalogued as separate IPs.

- **IP-003** — System: Microsoft Fabric — Lakehouse (`bronze`)
- Direction: inbound (read-only from this build's perspective)
- Protocol/mechanism: [STAGE-2-UPDATE — 2026-09-02]: `tedious` driver — a **separate**
  client library from `mssql` (used for `recon`, IP-002) — confirmed in M-008
  (fabricLakehouse.ts); this precision wasn't available at Stage 1
- Purpose: existing live NetSuite/CCC reference data, externally owned and ingested by a
  separate Fabric pipeline (confirmed 2026-08-28, not built by this project)
- Called by: M-008 (fabricLakehouse.ts, the sole direct caller) — reached from M-026
  (deterministicMatching.ts)
- Auth: [STAGE-2-UPDATE — 2026-09-02, backported from Session E]: AAD `ClientSecretCredential`
  (OAuth client-credentials flow) via `FABRIC_CLIENT_ID`/`FABRIC_CLIENT_SECRET`/
  `FABRIC_TENANT_ID`, token cached in-process and refreshed ~60s before expiry.
- Error handling: [STAGE-2-UPDATE — 2026-09-02]: nothing in M-008 catches anything — token
  acquisition, connection errors, and query-callback errors all propagate uncaught to the
  sole caller, M-026. This has a real downstream consequence: a Lakehouse outage cascades
  through M-026's transaction into M-017's batch loop (no per-document error isolation),
  so one bronze-read failure can abort an entire scheduled matching batch — not just the
  document being checked when it happened.

- **IP-004** — System: Microsoft Fabric — Warehouse (`silver`, `gold`)
- Direction: outbound (write to `silver.statement_line`), inbound (read from `gold` for
  reporting, currently unimplemented — see A01)
- Protocol/mechanism: [STAGE-2-UPDATE — 2026-09-02]: this application's own
  `silver.statement_line` writes (M-024 via M-003) are direct SQL inserts through the same
  connection as `recon` — **not** through dbt. `dbt`/`dbt-fabric` is not invoked anywhere
  in this codebase's own call graph (confirmed absent from Session A0's full file
  inventory); it presumably transforms data for/from this schema via a separate, external
  process this codebase doesn't own or call. This refines rather than contradicts Stage
  1's claim — dbt exists in the target architecture, just not as code this application
  itself runs.
- Purpose: shared normalization layer (`silver`) and existing reused Gold reporting layer
- Called by: M-003 (for the `silver` write path); N/A for `gold` (unimplemented, see A01)
- Auth: [STAGE-2-UPDATE — 2026-09-02]: not a genuinely separate fact from IP-002's — the
  `silver` write path shares M-003's exact same connection pool as `recon`, not an
  independent auth surface. Cataloguing IP-002/IP-004 as five-total "separate" integration
  points obscures that a connect failure breaks both simultaneously (see IP-002's Error
  handling / R-004).
- Error handling: [STAGE-2-UPDATE — 2026-09-02]: same connection-pool permanent-cache bug
  as IP-002 (R-004), since it's the same pool. Separately: `vendorSchema.ts` (M-041)'s
  Fabric DDL for per-vendor raw tables has no `IF NOT EXISTS` guard (unlike its SQLite
  counterpart), contradicting its own "idempotent" doc comment — currently unreachable
  (no code path exercises Fabric app-state for vendor-table creation in this build), so
  not promoted to the risk register, but sits latent under this integration point.

- **IP-005** — System: n8n
- Direction: inbound (triggers this build) / outbound (notifications)
- Protocol/mechanism: NOT DETERMINABLE FROM SOURCE (docs state its role, not the transport)
- Purpose: triggers the monthly Run Creation API call and sends completion notifications
  only — explicitly does not orchestrate extraction or matching itself
- Called by: N/A — n8n is the caller here, not the callee; this app's receiving endpoint is
  M-053 (`api/matching/run-batch/route.ts`), confirmed as the sole handler of this
  direction. Confirmed via Session A: no internal producer/consumer async boundary exists
  on this app's side — M-053 awaits M-017 synchronously within the same request.
- Auth: [STAGE-2-UPDATE — 2026-09-02, backported from Session D/E — **the most consequential
  finding in this entire Stage 2 pass**]: `/api/matching/run-batch` is **not** excluded from
  `proxy.ts` (M-043)'s session-cookie auth matcher the way `/api/health` (M-051) explicitly
  is (confirmed directly against the matcher regex, not just inferred). Every request to
  M-053 — including n8n's — must carry a valid browser session cookie or gets redirected to
  `/login` before the route handler ever runs. n8n, as an external machine-to-machine
  scheduler with no browser, has no documented way to obtain or present that cookie, and no
  compensating machine-auth mechanism (API key, shared secret) exists anywhere in source.
  **As coded, this build's only non-manual matching trigger path is unreachable by its own
  documented caller.** See `RISK_REGISTER.md` R-006 (P1) and `INVARIANT_CATALOGUE.md`
  IC-CANDIDATE-03.
- Error handling: [STAGE-2-UPDATE — 2026-09-02]: M-053 promises `{processed, skipped}` on
  success, but a genuine per-document exception (not just a held lock) inside M-017's loop
  is uncaught — it propagates to an unhandled 500 with zero partial-result reporting, and
  none of that batch's already-completed work is communicated back to n8n.

- System: Entra ID / company SSO — **no IP-NNN assigned (not integrated, per Stage 1)**
- Direction: N/A — not integrated
- Protocol/mechanism: N/A
- Purpose: stated end-goal auth mechanism; this build's actual v1 mechanism is
  username/password (M-001/M-054). The Sign In screen's "Sign in with company SSO" button
  is a disabled placeholder (`UI_SURFACE.md` unresolved gap #1), not a working integration
- Called by: N/A (not built)
- Auth: N/A (not built)
- Error handling: N/A (not built)

**IP-NNN IDs above are permanent for the life of this project**, assigned sequentially
IP-001–IP-005 at Stage 2 Session A, per BCE convention.
