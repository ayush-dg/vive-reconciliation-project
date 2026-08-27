# ARCHITECTURE.md — VIVE Statement Reconciliation (Bounded First Build)

**Version:** 1.3 (pending engineer sign-off on 2026-08-27 changes)
**Status:** DRAFT — awaiting sign-off per PBVI Human Accountability Gate
**Traces to:** `brief/REQUIREMENTS_BRIEF.md`, Phase 1 Interrogate Output v2, `docs/target-architecture/VIVE_Statement_Reconciliation_Architecture_v3_3.md` (decision register D1–D24)

## v1.3 Changelog (2026-08-27, same day as v1.2)

**New D-K** — two narrow, cheap reconciliations with
`brief/Reconciliation_Engine_Reusable_Components.docx`: `extracted.document` gains an
`artifact_type` column (constant `vendor_statement` for now); every pipeline stage
(validation, deterministic match, AI residual, exception wiring) returns a structured
result (`stage`/`status`/`candidate_ids`/`reason_codes`/`evidence`/`confidence`/
`requires_review`) instead of ad hoc pass/fail. Everything else in that brief (Run
Manager, generic Registry, Audit Ledger, Human Review Contract, Evaluation Harness,
Observability) remains deferred to BCE, unchanged from the prior discussion.

## v1.2 Changelog (2026-08-27)

1. **New D-J** — VIVE-specific intake data (documents, extraction attempts, per-vendor raw
   statement rows) moves to a new `extracted` schema, separate from `bronze`/`silver`/
   `gold`, which already host live NetSuite data. Silver stays shared — the normalized,
   vendor-agnostic `silver.statement_line` remains the one place VIVE and NetSuite data
   coexist by design.
2. **Per-vendor raw tables** — each vendor's statement lands in its own raw table
   (`extracted.stmt_<vendor_slug>`), preserving native column shape at that layer.
   Normalization to the shared `silver.statement_line` schema happens once, in Silver —
   matching, exceptions, and reporting remain vendor-agnostic and untouched by this change.
3. **Fabric sequencing** — Sessions 1–3 (auth, upload, extraction) build and test against
   local SQLite (Task 1.1's existing fallback); Fabric becomes required starting Session 4
   (NetSuite/CCC ingestion has no meaningful local mock). Migrations must be written in
   Fabric-compatible T-SQL from the start — SQLite is a same-shape local stand-in, not a
   separate dialect to design around.

## v1.1 Changelog (2026-08-26)

1. **D-B/D7 amended** — extraction-confidence floor removed from the arithmetic/retry gate;
   see INVARIANTS.md G2 (amended) for full detail.
2. **D-H amended** — collision handling for same vendor/period re-uploads is automatic
   version-chaining, not a human-reviewed flag (the flag was never implemented in the
   reference logic). See INVARIANTS.md S2/OD4.
3. **Fabric confirmed live** — Bronze (Lakehouse), Silver/Gold (Warehouse), `recon` (SQL
   database in Fabric) all run on Fabric now; no longer gated on access.
4. **New D-I** — upload and extraction are separate explicit user acts (extends D17's
   ingestion/reconciliation separation one step earlier).
5. **`ExtractionAttempt` entity** — confidence reframed as diagnostic metadata, not a gate;
   extraction-path/provider now a tracked field for reporting.

---

## 1. Problem Framing

**What this build solves:** a working, end-to-end slice of statement reconciliation —
sign-in, statement upload, AI-assisted extraction, deterministic-first matching against
VIVE's reference data, a flat exception list for anything that doesn't match, and simple
per-statement/per-reconciliation-cycle reporting.

**What this build explicitly does not solve:**
- No human review/approval workspace (no approve/dispute actions, no reviewer/approver
  separation, no dollar-threshold second approval)
- No formal Reconciliation Run object (no frozen input scope, no run versioning)
- No permanent audit ledger of human decisions (there are no human decisions to log yet —
  only system-generated matches and exceptions)
- No management reporting (no trend analysis, no cost reporting, no exception aging)
- No NetSuite write-back (unresolved at the SOW level regardless — out of scope either way)
- No multi-role access control (single user type)

**Why bounded this way:** this slice is built first, by the current engineering team, and
is deliberately scoped to hand off cleanly via BCE once additional engineers join to execute
the remaining enhancements (review workspace, formal runs, audit ledger, management
reporting). The boundary is a team-scaling and onboarding decision, not a technical
limitation — the deferred capabilities are real, planned, and already named in v3.3's
decision register; they are sequenced after this foundation, not designed away.

---

## 2. Key Design Decisions

### D-A — Slice boundary: sign-in → upload → extract → match → flat exceptions → simple report
**Decision:** Build only these six capabilities now. Defer review/approval workspace, formal
runs, audit ledger, and management reporting to a BCE-driven enhancement phase.
**Rationale:** This build is delivered ahead of additional engineers joining the project.
Structuring it as a clean, boundable foundation lets BCE onboard new engineers against a
completed, working slice rather than a partially-built monolith with unfinished workflow
logic threaded through it.
**Alternatives rejected:** Building the full v3.3 scope in one pass — rejected because it
delays a working deliverable and produces a larger, harder-to-onboard-into codebase for the
engineers who join later, with no offsetting benefit since this build has no dependency on
the deferred capabilities.

### D-B — Adopt v3.3's data-pipeline decisions as-is: D7, D9, D17, document-level `legal_entity_id`
**Decision:** This build implements, unchanged from v3.3:
- **D7 (amended 2026-08-26)** — structural + arithmetic gate runs after the
  `extracted.extraction_attempt` write (relocated per D-J, was `bronze.extraction_attempt`);
  on failure, re-submit for extraction (max 2 attempts), then flag `OCR_LOW_CONFIDENCE`.
  The extraction-confidence floor is no longer part of this gate — a low-confidence but
  structurally/arithmetically valid row proceeds to Silver, with confidence carried as
  metadata rather than a retry/block trigger. See INVARIANTS.md G2.
- **D9** — NetSuite and CCC reference data ingested via an internally-owned daily batch job,
  Bronze→Silver; matching never calls either API live.
- **D17** — document ingestion and reconciliation execution remain separate acts; a file
  landing in storage does not implicitly trigger matching.
- **Document-level `legal_entity_id`** — tagged on every `extracted.document` record at
  intake (relocated from `bronze.document` per D-J; same guarantee, new schema home).
  independent of whether a formal Run object exists.
**Rationale:** These are foundational data-pipeline decisions that don't depend on which
workflow features exist above them (review workspace, runs, etc.). They're already settled
by v3.3's decision register; re-deciding them here would be redundant and would risk drifting
from the target architecture for no reason.
**Alternatives rejected:** None considered — re-opening settled infrastructure decisions
with no new information would violate the Explore→Decide gap check (no new constraint
surfaced that would justify revisiting them).

### D-C — Defer to BCE: D18–D20 (formal Run), D12 (optimistic locking), D10/§21-5 (write-back), full D11 (Gold/Power BI)
**Decision:** This build does not implement a Reconciliation Run object, `ROWVERSION`-based
concurrency control, NetSuite write-back, or the full Gold/Power BI reporting layer.
**Rationale:** Each of these exists to serve a capability not present in this build — Run
scoping serves formal batch traceability and versioned re-matching; optimistic locking
serves concurrent human reviewers/approvers; write-back is unresolved at the SOW level
regardless; full Gold/Power BI serves trend and cost management reporting. Building any of
these now would add real complexity in service of capabilities this build doesn't expose.
**Alternatives rejected:** Building these now "in case BCE needs them sooner" — rejected
because it front-loads complexity for unused capability and delays the actual deliverable.
The data model (§8 below) is deliberately shaped so BCE can add these without a rebuild,
which is judged sufficient forward-compatibility without building the features themselves.
**Note (2026-08-17):** D-D was subsequently updated to reuse the Gold *storage layer*
(materialized Fabric Warehouse tables per D11) directly for this build's simple report.
This is narrower than what's deferred here — Power BI dashboards, trend/cost/management
reporting, and exception-aging reports remain BCE-scope; only the underlying data layer
choice changed, not the reporting feature set.

### D-D — Reporting reads from Gold (v3.3 D11), not `recon` directly [UPDATED 2026-08-17]
**Decision:** This build's simple per-statement/per-reconciliation-cycle report reads
directly from the Gold layer as already defined in v3.3 (materialized Fabric Warehouse
tables, per D11), not from `recon` directly, and not from a custom scaled-down
Gold-equivalent structure. **This reverses the original v1.0 decision** ("lightweight
Gold-equivalent, not full Gold Warehouse") based on the engineer's explicit resolution:
"it will be gold only."
**Rationale:** v3.3's D11 establishes that `recon` must stay isolated from reporting-query
load — reusing the existing Gold layer directly, rather than building a separate
bounded-build-specific reporting structure, avoids maintaining two parallel reporting
patterns and keeps this build consistent with the target architecture's data layer from
the start.
**Alternatives rejected:**
- *Reads directly from `recon`* — rejected, same rationale as before: contradicts D11's
  isolation principle and D3's treatment of `recon` as a live transactional store.
- *A custom, scaled-down Gold-equivalent (view or lightweight scheduled table)* —
  originally decided (v1.0), now superseded by the engineer's explicit resolution to
  reuse Gold as-is rather than build a bounded-build-specific alternative.
**Note:** This resolves ARCHITECTURE.md §6's open question on reporting structure — Gold
is the existing v3.3 materialized Fabric Warehouse layer, queried directly for this
build's simple report. This does not imply Power BI dashboards or full management
reporting (trends/cost/aging) are now in scope — those remain BCE-scope per the original
slice boundary (D-A); only the underlying data layer choice changed.

### D-E — Single user role, no in-application role differentiation
**Decision:** This build has one user type — no reviewer/approver distinction, no separate
admin role.
**Rationale:** Direct consequence of D-A/D-C — without a review/approval workspace, there's
no brief-driven basis for more than one role.
**Alternatives rejected:** None — this follows mechanically from D-C, not an independent
choice.

### D-F — Multi-entity handling: `legal_entity_id` at document level; access scoping deferred
**Decision:** Entity scoping rides on the document record (per D-B), satisfying data-model
needs. Whether a user sees all entities at once or via a selector is deferred to UI Discovery
as a screen-design question, not resolved here.
**Rationale:** v3.3 already answers the data-tagging question; it does not answer the
access-scoping question, and with only one user role (D-E), access scoping is a UI-layer
decision, not an architectural one.
**Alternatives rejected:** None — this is a placeholder, not a decision between alternatives.

### D-H — Same vendor/period collision handling without a Run object [AMENDED 2026-08-26]
**Decision:** Identical-file re-uploads are deduplicated by content hash — not re-extracted,
not re-reconciled (unchanged). A *different* document (different hash) landing for the same
vendor/period/entity is automatically **version-chained**: the new document becomes the
latest version (`is_latest_version` = true), the prior document is marked superseded
(`previous_statement_id` links back to it). **This replaces the original human-review-flag
design** — that flag ("possible duplicate/correction — review before processing") was never
implemented in the reference logic; version-chaining is what the current system actually
does, with no human step. Full disambiguation logic beyond "which version is current" is
still deferred to BCE once the Run object exists.
**Rationale:** Without a Run object, there's no architectural concept of "this is the
authoritative attempt for vendor X, period Y" — version-chaining gives a mechanical answer
(latest wins) without requiring a human decision on every re-upload, which is simpler to
operate at volume but provides no signal when a "new version" is actually an unrelated,
genuinely conflicting statement rather than a correction.
**Alternatives rejected:**
- *Process both regardless* — rejected because it would let two statements' matches/exceptions
  coexist with nothing marking which is authoritative, directly recreating the ambiguity the
  Run object exists to prevent.
- *Reject the second document outright* — rejected because a legitimate reissued/corrected
  statement is a real, expected business event, not an error condition.
- *Human-reviewed flag (original 2026-08-17 design)* — superseded 2026-08-26: not what the
  reference implementation actually does, and version-chaining is the simpler mechanism to
  build against for this bounded scope. **Flagged, not silently accepted:** this removes the
  human checkpoint the original design provided for genuinely conflicting (non-correction)
  statements — worth Vaishali/Vartan confirming this trade explicitly.

### D-I — Upload and extraction are separate explicit acts [NEW 2026-08-26]
**Decision:** Uploading a document registers it only (content-hash check, `extracted.document`
record created — see D-J). Extraction is a distinct, explicit user-triggered action on that
document — it does not run automatically on upload.
**Rationale:** Extends D17's existing separation (ingestion vs. reconciliation are separate
acts) one step earlier — a user may want to upload several statements before committing
extraction spend/time on any of them, and this gives an explicit checkpoint consistent with
D17's same reasoning.
**Alternatives rejected:** Auto-extract on upload — rejected as inconsistent with D17's
already-established principle that landing a file in storage should not implicitly trigger
downstream processing.

### D-J — VIVE intake data lives in a new `extracted` schema; per-vendor raw tables [NEW 2026-08-27]
**Decision:** `bronze`/`silver`/`gold` already host live NetSuite data on Fabric. Rather than
add VIVE-specific document/extraction tables into `bronze` alongside that, this build
introduces a new `extracted` schema, scoped entirely to VIVE statement intake:
- `extracted.document` — the document registry (content hash, `legal_entity_id`,
  version-chaining per D-H) — same fields previously described as `bronze.document`,
  relocated, not redesigned.
- `extracted.extraction_attempt` — the append-only attempt log (previously
  `bronze.extraction_attempt`), same G1/S10 guarantees, now scoped to this schema.
- `extracted.stmt_<vendor_slug>` — one raw table per vendor (e.g.
  `extracted.stmt_fred_beans`, `extracted.stmt_keystone`), preserving each vendor's native
  extracted column shape rather than forcing a shared shape this early in the pipeline.

Normalization from these per-vendor raw tables into the single, shared
`silver.statement_line` still happens in Silver, per the existing "normalization belongs
in Silver, not at match time" principle — matching, exceptions, and reporting read only
`silver.statement_line` and are entirely unaffected by which vendor a line came from.
**Rationale:** Keeps VIVE's intake surface out of `bronze`'s namespace (avoiding collision
with existing NetSuite tables there), while preserving vendor-native shape at the raw
layer without multiplying enforcement surface downstream — G1/S10 apply per-table under
`extracted`, but S11 (amount immutability) and matching/reporting logic stay singular,
against `silver.statement_line` only.
**Alternatives rejected:**
- *Per-vendor tables all the way through Silver* — rejected for this build: multiplies
  G1/S10/S11 enforcement points across N tables and requires matching/exceptions/reporting
  to become vendor-routed, a materially larger change with no benefit this build needs.
  Revisit if/when the reusable-components effort (`brief/Reconciliation_Engine_Reusable_
  Components.docx`) formally scopes a per-vendor adapter layer.
- *Adding VIVE tables directly into `bronze`* — rejected: risks naming collision and
  namespace confusion against existing live NetSuite `bronze` tables.

### D-K — Reusable-components alignment: artifact_type field, pipeline result contract [NEW 2026-08-27]
**Decision:** Per `brief/Reconciliation_Engine_Reusable_Components.docx`, two narrow,
cheap structural choices are made now, both consistent with that brief's own non-goals
(no generic business-schema, no rules DSL, no config language built prematurely):

1. **`extracted.document` gains an `artifact_type` column**, constant-valued
   `vendor_statement` for this build. This costs one column and zero new logic — it just
   means the table doesn't silently assume "the only thing ever registered here is a
   vendor statement," which is the specific hard-coding the brief flags as the thing to
   avoid, without building any actual multi-artifact-type handling now.
2. **Every pipeline stage (validation gate, deterministic match, AI-assisted residual,
   exception wiring) returns a structured result** — `stage`, `status`, `candidate_ids`,
   `reason_codes`, `evidence`, `confidence` (where applicable), `requires_review` — instead
   of ad hoc pass/fail booleans or free-text strings. This is the same information each
   stage already needs to produce for its own task's test cases; it's a shape decision, not
   new functionality.

**Rationale:** Both changes are things this build's own tasks were going to produce
information for anyway (an extraction attempt already has a status and evidence; a match
attempt already has candidates and a reason). Naming that output consistently costs
nothing extra now and is the difference between "reusable without a rewrite" and "reusable
after a rewrite" per the brief's own test. Everything else the brief describes — a real
Run Manager, a generic Document Registry service, an Audit Ledger, a Human Review Contract,
an Evaluation Harness, Observability standards — remains genuinely deferred, per D-C, to
BCE or a parallel track; this build does not attempt any of them.
**Alternatives rejected:**
- *A generic `business_metadata` JSON field replacing `vendor_id`/`statement_period`* —
  rejected for this build: the brief explicitly warns against building one canonical
  business schema before a second use case exists to validate the abstraction against.
  `vendor_id`/`statement_period` stay as named columns; `artifact_type` is the only
  concession to future extensibility.
- *Building the full Run Manager / Registry / Pipeline Framework / Audit Ledger now* —
  rejected: unchanged from the prior discussion — these are genuinely new, unbuilt
  capabilities in this repo, not existing VIVE-coupled code needing decoupling, so BCE
  building them generic from day one costs nothing extra. Re-scoping Build1 to build them
  now would extend the timeline for no benefit this build needs.

### D-G — Exception schema forward-compatibility (Explore evaluation criterion, not a fact)
**Decision:** The exception data model in this build must be structured so that BCE can add
owner, aging-clock, and run-reference fields later as additive schema changes, not a rebuild.
**Rationale:** This build's exceptions are a flat, ownerless list by design (D-C), but the
underlying entity is the same one BCE will extend. Structuring it defensively now (e.g.,
nullable fields reserved conceptually, no encoding that assumes "no owner" as a permanent
property of the entity) avoids a costly migration later.
**Alternatives rejected:** Building today's exception schema without regard for future
extension — rejected because it directly risks the "build now, throw away at BCE handoff"
failure mode identified in Interrogate.

---

## 3. Challenge My Decisions

**D-A (slice boundary):** *Strongest argument against —* shipping a reconciliation tool with
no review/approval step means nothing produced by this build can be acted on by AP without a
second, disconnected process outside the system, which may reduce this build's real-world
value until BCE ships the workspace. *Verdict: valid concern, not a reason to reject the
decision.* The system's value in this phase is proving extraction and matching quality against
real data, not full production operation — BCE's job is exactly to close this gap next.

**D-B (adopt v3.3 pipeline decisions as-is):** *Strongest argument against —* accepting D7/D9/D17
without re-examination assumes v3.3 is correct for this narrower slice too; it's possible the
full-scope architecture over-specifies for a smaller build. *Verdict: rejected.* These are
data-correctness and data-integrity decisions (arithmetic validation, live-call avoidance,
ingestion/execution separation) that apply at any scope — nothing about narrowing the slice
weakens their rationale.

**D-C (defer formal Run, locking, write-back, full Gold):** *Strongest argument against —*
without a Run object, there's no explicit scope boundary for a given reconciliation attempt;
two uploads for the same vendor/period could produce ambiguous or overlapping results with no
formal object to disambiguate them. *Verdict: valid and unresolved.* This is a real gap this
build must still handle at the implementation level (see Open Questions, §6) even without the
full Run object — it doesn't require deferring the decision, but it does require an answer
before Phase 3 execution planning.

**D-D (Gold layer reuse, not recon-direct):** *Strongest argument against —* introducing a
Gold dependency at all is added infrastructure for a "simple report," when a direct `recon`
read would be far cheaper to build for a low-volume, single-team-only tool. *Verdict:
rejected.* The cost of unwinding a `recon`-coupled reporting pattern once BCE adds
concurrent human approvers is higher than the cost of reusing Gold now — this is exactly
the kind of decision the forward-compatibility principle (D-G) is meant to protect against.
*Resolved 2026-08-17:* the engineer's explicit direction ("it will be gold only") settles
this in favor of reusing the existing Gold layer directly rather than building a
bounded-build-specific alternative, removing the earlier "how much Gold infrastructure is
justified" tension entirely — the answer is now "the same Gold that already exists."

**D-E (single role):** *Strongest argument against —* if BCE's role differentiation is known
to be coming, building even placeholder role infrastructure now could ease that transition.
*Verdict: rejected.* Per PBVI-011 placeholder convention, this is correctly deferred rather
than half-built; a placeholder role with no real permission boundaries would be dead weight,
not forward-compatibility.

**D-F (entity tagging, access scoping deferred):** *Strongest argument against —* deferring
access-scoping to UI Discovery risks discovering a real architectural need (e.g., entity-based
data partitioning at the query layer) too late, after Explore/Decide has closed.
*Verdict: partially valid — noted as a risk, not grounds to resolve now.* Given single-role
access (D-E), the risk is bounded: worst case is a UI Discovery finding that becomes a
Phase 2 loop-back, not a full architecture rework.

**D-G (exception forward-compatibility):** *Strongest argument against —* "structure it so
it's extensible" is vague enough to not actually change what gets built, making it an
unfalsifiable decision rather than a real constraint. *Verdict: valid — needs sharpening
before Phase 3.* Execution planning must translate this into a concrete schema constraint
(e.g., specific nullable columns or a documented extension point), not left as a principle.

---

## 4. Key Risks

1. **No Run-equivalent scope boundary for the "which attempt produced this" question** —
   D-H (amended) resolves the immediate collision-handling behavior via automatic
   version-chaining, but there is still no architectural concept of "which processing
   attempt" a given match or exception traces back to, since that's exactly what the
   deferred Run object (D18–D20) provides. **New risk surface from the amendment:**
   version-chaining has no human checkpoint at all now, so a genuinely conflicting (not
   corrective) statement for the same vendor/period silently supersedes the prior one with
   no flag raised. This is a real gap for BCE to close, and a sharper one than before the
   2026-08-26 amendment — worth explicit sign-off rather than treating as equivalent risk.
2. **Reporting layer** — RESOLVED 2026-08-17: reuses the existing v3.3 Gold layer directly
   (D-D), removing the earlier ambiguity about how much reporting infrastructure to build.
3. **BCE handoff quality depends on schema discipline this build can't fully verify now** —
   RESOLVED 2026-08-17: D-G's forward-compatibility goal is now concrete — nullable
   owner/aging/run_reference columns are added to the Exception schema now, even while
   unused, per the engineer's explicit direction. This removes the earlier vagueness risk;
   remaining verification is a Phase 3 implementation detail, not an open design question.
4. **Access-scoping deferral could surface a real architectural need late** — per the D-F
   challenge, if UI Discovery reveals users genuinely need entity-partitioned access (not just
   a screen filter), that's a Phase 2 loop-back, not a cosmetic fix.

---

## 5. Key Assumptions

- Extraction, matching, and reporting logic already validated in v3.3 (models, confidence
  floors, matching passes) are being inherited as designed — this build is a scope reduction
  of what gets *exposed*, not a re-validation of what's already been engineered.
- The single user role in this build corresponds to whoever operates the system pre-BCE
  handoff (likely an internal engineering/ops user, not the eventual AP end user) — this
  hasn't been explicitly confirmed and should be checked before further build work.
- BCE's eventual audience (new engineers) will have access to this ARCHITECTURE.md and the
  full v3.3 document as onboarding material — the forward-compatibility decisions (D-G) rely
  on that continuity actually happening.
- **Data baseline confirmed (UI_SURFACE.md sign-off):** Migrated only, no Seeded component —
  all data resides in cloud infrastructure (Azure/Fabric). SEED_DATA.md production is
  correctly skipped per the PBVI-011 conditional.

---

## 6. Open Questions (Phase 3 depends on these)

1. RESOLVED 2026-08-17 — Gold-equivalent structure: reuses the existing v3.3 Gold layer
   directly (see updated D-D). No longer open.
2. RESOLVED 2026-08-17 — D-G's forward-compatibility: nullable owner/aging/run_reference
   columns are added to the Exception schema now, per engineer direction. No longer open.
3. PARTIALLY RESOLVED 2026-08-17 (INVARIANTS.md OD5) — multiple named users confirmed,
   read as sharing the single existing role (not full role differentiation). Real
   per-user authentication/identity is required; entity-scoped access (D-F) remains open.
4. REOPENED 2026-08-26, AMENDED (INVARIANTS.md OD4) — the duplicate/correction flag as
   originally resolved (read-only, visible in Exceptions/Exception Detail) was never
   actually implemented in the reference logic. Replaced with automatic version-chaining
   (D-H, amended) — no flag, no human step. The "possible duplicate/correction" exception
   type is removed from the Exceptions taxonomy accordingly (see UI_SURFACE.md).
5. NEW 2026-08-26 — confirm G2's confidence-floor removal (see INVARIANTS.md G2) and D-H's
   version-chaining-without-human-flag (see above) are both intentional, accepted trades —
   not yet signed off as of this revision.

---

## 7. Future Enhancements (Parking Lot — Conscious Deferrals)

| Deferred item | Rationale for deferring |
|---|---|
| Review/approval workspace (reviewer/approver separation, dollar thresholds) | BCE-scope; no basis to build without the workflow it serves |
| Formal Reconciliation Run object (D18–D20) | BCE-scope; requires the run-scoped features (approval, versioning) this build doesn't yet expose |
| Optimistic locking / `ROWVERSION` concurrency (D12) | Moot without concurrent human reviewers/approvers |
| Permanent audit ledger of human decisions | No human decisions exist yet to log beyond system-generated matches |
| NetSuite write-back (D10/§21-5) | Unresolved at SOW level; out of scope regardless of this build's boundary |
| Power BI dashboards, trend/cost/management reporting, exception aging | Serves reporting needs beyond this build's scope; Gold *data layer* itself is now reused directly (D-D), only the dashboard/feature layer remains BCE-scope |
| Multi-role access control | No role differentiation exists without the deferred review workspace |
| Full duplicate/correction disambiguation beyond "latest version wins" (e.g., detecting a version-chained document is actually an unrelated conflicting statement, additive-statement handling) | D-H (amended 2026-08-26) auto-chains versions now with no human checkpoint; distinguishing correction-vs-conflict depends on the Run object BCE will add |
| Live NetSuite/CCC pull as an alternative matching mode | Raised 2026-08-17 during Phase 2: a future matching mode may query NetSuite/CCC live instead of exclusively via Silver snapshot. This directly supersedes D-B's adoption of v3.3's D9 ("matching never calls either API live") if implemented, and must be re-evaluated against reproducibility requirements (G2, v3.3's own reproducibility rationale) before being enabled. INVARIANTS.md's corresponding Global invariant was removed at engineer's direction per this same discussion — this entry exists so the two documents don't silently diverge. |
| Entity-based access partitioning at query layer (if UI Discovery surfaces the need) | Deferred pending D-F's UI Discovery finding |

---

## 8. Data Model — First-Class Entities (This Build's Scope)

*(Schema note, 2026-08-27 per D-J: `bronze`/`silver`/`gold` already host live NetSuite
data. VIVE-specific intake now lives in a new `extracted` schema, kept separate to avoid
namespace collision. `silver.statement_line` remains the one shared, vendor-agnostic
table where VIVE and NetSuite data coexist by design.)*

| Entity | Represents | Forward-compatibility note |
|---|---|---|
| **Document** (`extracted.document`) | An uploaded vendor statement PDF — vendor, legal entity, statement period, status, version, content hash, **`artifact_type` (constant `vendor_statement`, per D-K)** | Already carries `legal_entity_id`; no change needed for BCE. Relocated from `bronze.document` (D-J) — same fields, new schema, plus `artifact_type` (D-K) |
| **ExtractionAttempt** (`extracted.extraction_attempt`) | One extraction pass over a Document — raw output, confidence (diagnostic metadata only, amended 2026-08-26 — no longer a gate), structural/arithmetic-gate result, extraction path/provider used (`python_library_pdfplumber` / `claude_sonnet` / `pdfplumber_fallback`), attempt number (max 2) | Self-contained; BCE unlikely to need to extend. Provider field newly required to support the Document Detail extraction-method summary (UI_SURFACE.md). Relocated from `bronze.extraction_attempt` (D-J) |
| **VendorStatementRaw** (`extracted.stmt_<vendor_slug>`, one table per vendor) [NEW 2026-08-27] | Raw extracted rows in each vendor's native column shape, prior to normalization | New entity per D-J. BCE's future generic Document Registry (per the reusable-components brief) would sit above this layer as an adapter target, not replace it — table-per-vendor pattern intentionally kept simple (no dynamic schema registry) for this bounded build |
| **StatementLine** (`silver.statement_line`) | A normalized, extracted invoice line from a statement — the single vendor-agnostic shape every `extracted.stmt_*` table normalizes into. Blank-amount (credit/payment) lines now reach Silver (2026-08-26) rather than being pre-emptively diverted to `EXTRACTION_INCOMPLETE` | Should not assume "final" status — BCE's Run object will eventually reference lines by way of matches. Coexists here with any NetSuite-derived Silver tables already present — shared schema by design |
| **ReferenceSnapshot** (Silver) | Daily Bronze→Silver pull of NetSuite open invoices / CCC repair orders, now live on Fabric | Unaffected by this build's scope boundary |
| **Match** (`recon`) | Result of deterministic or AI-assisted matching between a StatementLine and reference data. **Returned via the structured pipeline result contract (D-K): stage, status, candidate_ids, reason_codes, evidence, confidence, requires_review** | Must not assume a Run always exists — BCE will later add a run reference; this build's Match records should be structured so that field is additive, not retrofitted |
| **Exception** (`recon`) | An unmatched or ambiguous StatementLine, tracked as a flat list item. **"Possible duplicate/correction" removed as an exception type (2026-08-26)** — collisions are now auto-resolved by version-chaining (D-H) before reaching Exceptions, not surfaced as an exception. Also produced via the D-K result contract | RESOLVED 2026-08-17: nullable `owner`, `aging_started_at`, and `run_reference` columns are added to this table now, even while unused, per engineer direction — no longer a deferred principle, an actual schema decision |
| **ReportView** (Gold, reused directly per updated D-D) | Existing v3.3 Gold layer (materialized Fabric Warehouse tables), queried directly for this build's simple per-statement/per-cycle results | No longer bounded-build-specific — reuses the target architecture's Gold layer as-is; Power BI dashboards and trend/cost/aging features remain BCE-scope |

---

## Engineer Sign-Off

**Decision owner:** Vaishali
**Date:** 2026-08-17
**Signature / confirmation:** [x] I confirm this architecture is accurate to my decision and reasoning as stated.

**Signed off with open items carried forward to Phase 3 (updated 2026-08-17):**
- §6.1 (Gold structure), §6.2 (D-G schema fields), §6.4 (duplicate-flag UI) — all RESOLVED,
  no longer carried forward.
- §6.3 / OD5 (user/entity access model) — partially resolved; entity-scoped access (D-F)
  remains genuinely open, carried into Phase 3 as a non-blocking item.
- All INVARIANTS.md Open Decisions (OD1–OD4) are now resolved; OD5 partially resolved,
  matching this document's §6.3 status.

---

## v1.1 Sign-Off Addendum (2026-08-26)

**Decision owner:** Vaishali
**Date:** 2026-08-26
**Status:** DRAFT — pending sign-off. Two items carried over from INVARIANTS.md v1.3
specifically need confirmation before this version is final:
1. D-B/D7 confidence-floor removal (see G2).
2. D-H version-chaining without a human checkpoint (see S2/OD4).

**Not requiring separate sign-off:** Fabric-live confirmation, D-I (upload/extract
separation), ExtractionAttempt provider-field addition — these are lower-risk,
mechanical updates.

---

## v1.2 Sign-Off Addendum (2026-08-27)

**Decision owner:** Vaishali
**Date:** 2026-08-27
**Status:** DRAFT — pending sign-off. D-J (extracted schema, per-vendor raw tables) is a
new structural decision — not carried forward from a prior flag, but new enough to note
explicitly:

1. **D-J** — confirms Option A (per-vendor tables at raw layer only, unified
   `silver.statement_line`) over Option B (per-vendor all the way through Silver).
   Revisit if the reusable-components effort later requires per-vendor Silver.
2. **Fabric sequencing** — confirms Sessions 1–3 build/test locally (SQLite fallback),
   Fabric required starting Session 4. Migrations must be Fabric-compatible T-SQL from
   the start.

**Still outstanding from v1.1 (unchanged, not resolved by this revision):**
1. D-B/D7 confidence-floor removal (see G2).
2. D-H version-chaining without a human checkpoint (see S2/OD4).

---

## v1.3 Sign-Off Addendum (2026-08-27, same day as v1.2)

**Decision owner:** Vaishali
**Date:** 2026-08-27
**Status:** DRAFT — pending sign-off.

**New this revision:** D-K (reusable-components reconciliation — `artifact_type` column,
pipeline result contract). Low risk — additive fields and a return-shape convention, not a
new behavioral trade — but worth explicit confirmation that this is the right amount of
generalization for now (not too much, not too little) before it propagates through Session
5's actual matching implementation.

**Still outstanding, unresolved by this or the v1.2 revision:**
1. D-B/D7 confidence-floor removal (see G2).
2. D-H version-chaining without a human checkpoint (see S2/OD4).
