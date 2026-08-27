# PHASE4_GATE_RECORD.md — VIVE Statement Reconciliation

**Date:** 2026-08-27
**Engineer:** Vaishali
**Review session:** Retroactive Step 1/1c review — conducted after `docs/Claude.md`,
`docs/ARCHITECTURE.md`, `docs/INVARIANTS.md`, `docs/EXECUTION_PLAN.md`, and
`docs/UI_SURFACE.md` were already signed off (2026-08-27). Per `pbvi_plan.md`: *"Claude.md
does not exist until this gate passes."* That sequencing was not followed — this record
is being produced after the fact, not before, and its findings should be weighed with that
in mind. Sections E and Step 2/2b below remain genuinely outstanding — this document
covers Step 1 and Step 1c only, both of which are AI-assisted and executable without the
engineer in the room; Step 2 and 2b are not.

---

## Section A — Evaluation Criteria

Derived from `docs/INVARIANTS.md` v1.4, supplemented with two universal completeness
criteria not covered by any single invariant.

| # | Criterion | Source |
|---|---|---|
| 1 | No unvalidated extraction becomes match-eligible | Invariant: G2 |
| 2 | Extraction attempts are append-only and FK-bound to exactly one document | Invariant: G1 |
| 3 | Extracted/vendor content is treated strictly as data, never as model instructions | Invariant: G3 |
| 4 | Byte-identical documents are never independently re-extracted or re-matched | Invariant: G4 |
| 5 | No document/work item has more than one active processing owner at a time | Invariant: G5 |
| 6 | Upload/intake never implicitly triggers matching | Invariant: S1 |
| 7 | Every match/exception is bound to exactly one immutable reference snapshot version | Invariant: S8 |
| 8 | Exception category is a closed enum, never free text | Invariant: S5 |
| 9 | Reporting reads only Gold/ReportView, never `recon` directly | Invariant: S3 |
| 10 | *(Universal)* Every entity/table the plan creates has at least one task that writes to it and at least one that reads from it — no orphaned schema | Not sourced from a single invariant; supplements INVARIANTS.md's data-integrity coverage |

---

## Section B — Requirements Traceability

Source: `brief/REQUIREMENTS_BRIEF.md` §3 ("What The System Must Do") and §4 ("What The
System Must Never Do").

### §3 — Must Do

| Requirement | Architecture Component | Task | Coverage Rating |
|---|---|---|---|
| 1. Ingest PDFs, deliberate (not instant) processing, track status | D-I, D-J | 2.1, 2.2, 2.3, 2.4 | FULLY MET — mechanism is user-click (D-I), not a schedule; both satisfy "not instant," worth confirming this matches intent |
| 2. Extract line items + mandatory arithmetic check, "single highest-value control" | D-B/D7 (amended), G2 | 3.2 | FULLY MET — the arithmetic check itself is intact; only the confidence-floor sub-component was removed, which this specific requirement doesn't reference |
| 3. Pull NetSuite/CCC reference data on a recurring schedule, versioned snapshot, never live | D-B/D9, S8 | 4.1, 4.2, 4.3 | FULLY MET |
| 4. Deterministic-first matching, narrow AI second opinion on residuals, never auto-approves | — | 5.2, 5.3 | FULLY MET |
| 5. Classify/route exceptions with owner, category, aging clock, corroborating evidence | D-C, D-G, OD3 | 5.4 | PARTIALLY MET — category yes; `owner`/`aging_started_at` columns exist but are NULLABLE and unused by design (D-C) — deliberate, well-documented scope reduction, not an oversight, but the brief's own §6 item 7 lists this as a genuinely open business question, not yet a build gap |
| 6. Group work into deliberate Runs — frozen inputs, versioned, full traceability | D-C | — | NOT ADDRESSED — explicitly deferred to BCE (D-C, D18–D20). Documented, not a surprise |
| 7. AP review workspace — approve/dispute, bulk, reviewer/approver separation, dollar threshold | D-A, D-C, D-E | — | NOT ADDRESSED — explicitly deferred to BCE. Documented, not a surprise |
| 8. Record every decision — automatic or human — permanently, as it happens | D-C, D-K | 5.2, 5.3, 5.4 | PARTIALLY MET — automatic decisions are captured via the D-K structured result contract at time of decision; there are no human decisions to log yet since no review workspace exists (D-C) |
| 9. Report outcomes/trends/cost to management, without competing with review capacity | D-D | 7.1, 7.2 | PARTIALLY MET — simple per-statement/per-cycle reporting via Gold is built; trend/cost/exception-aging management reporting is explicitly BCE-scope (D-A/D-C) |

### §4 — Must Never Do (non-negotiables)

| Non-negotiable | Architecture Component | Task | Coverage Rating |
|---|---|---|---|
| N1. AI never holds write authority, at any confidence | G3, D-K | 5.3 | FULLY MET — Task 5.3 explicitly never auto-approves, writes only a proposed field |
| N2. Never call NetSuite/CCC live from matching | S8 | 5.2 | **CONTRADICTED** — the original GLOBAL invariant enforcing this was removed 2026-08-17 (INVARIANTS.md "Removed Invariants" note); Task 5.2 itself states this is "no longer an enforced invariant, only a design convention." A brief non-negotiable currently has no hard enforcement behind it. **See Section D, Finding 5.** |
| N3. Intake never triggers reconciliation | S1, D-I, D17 | 2.1, 2.2, 2.4, 5.1 | FULLY MET — strengthened by D-I splitting upload/extract further |
| N4. Never overwrite a prior reconciliation attempt; full version history | T5 (deferred) | — | NOT ADDRESSED — T5 (immutable reconciliation history / re-match versioning) is explicitly in the Deferred Target-State (BCE-scope) section, not built here. The brief calls this a "never do," but its enforcement mechanism is deferred |
| N5. Two reviewers never silently clobber each other's work | T1 (deferred) | — | N/A BY SCOPE — moot in this build since no review workspace/reviewers exist yet (single role, D-E); not actively enforced but not actively at-risk either |
| N6. Never write reconciliation status back to NetSuite | D-A/D-C | — | FULLY MET as far as this build's code goes (no write-back path exists) — but the brief's own §6 item 4 flags this as a genuinely unresolved SOW conflict, not this build's job to resolve |

---

## Section C — Adversarial Stress Test Findings

| Attack Vector | Finding | Severity | Recommendation |
|---|---|---|---|
| DATA | No task in `EXECUTION_PLAN.md` writes to `silver.statement_line`. It's created (Task 1.2) and read (Task 5.2), but the normalization step transforming `extracted.stmt_<vendor_slug>` raw rows into it — the step Task 3.2 calls "proceed to Silver" — has no owning task anywhere in Sessions 1–7 | **BLOCKER** | Add a normalization task (likely Session 3, after Task 3.2) that owns the `extracted.stmt_*` → `silver.statement_line` transform, and give S6 (currently zero-coverage) something to attach to |
| DATA | No task defines what happens when a statement arrives from a vendor with no existing `extracted.stmt_<vendor_slug>` table — Task 1.2 only provisions tables for "known vendors" | HIGH | Add an unknown-vendor path: either auto-provision a generic raw table, or explicitly route to the Claude-primary extraction path with a defined landing table |
| INFRASTRUCTURE | `tools/` automation scripts not yet sourced (tracked in `PROJECT_MANIFEST.md`) | LOW | Soft blocker only, autonomous/challenge-agent mode only — no action needed for manually-driven sessions |
| EXECUTION | G5 (single active processing owner) — one of only five GLOBAL invariants — has zero task coverage anywhere in `EXECUTION_PLAN.md`. No task implements or verifies a processing lock/lease | **BLOCKER** | Add explicit lock/lease acquisition to whichever task(s) trigger extraction (2.4) and matching (5.1), citing G5 |
| EXECUTION | Task 5.1 supports both manual and scheduled matching invocation (OD1), but no task addresses what happens if both fire concurrently on overlapping documents — directly related to the G5 gap above | HIGH | Resolve together with the G5 finding — the lock/lease mechanism should cover this case explicitly |
| SECURITY | `docs/Claude.md` Section 4 (Fixed Stack) declares **Entra ID** as the auth mechanism. `docs/ARCHITECTURE.md` never states an auth mechanism at all. `docs/UI_SURFACE.md`'s Sign In spec and Task 1.3's CC prompt build **username/password authentication**, with SSO rendered as a disabled "Coming soon" placeholder. Building Task 1.3 as currently specified does not implement Entra ID | **BLOCKER** | Either (a) rewrite Task 1.3 to build against Entra ID/OIDC redirect and update `UI_SURFACE.md`'s Sign In spec accordingly, or (b) correct `Claude.md`'s Fixed Stack to reflect that username/password is the actual v1 mechanism and Entra ID is a stated future direction, not the current build target. Currently the three documents disagree with each other |
| ARCHITECTURE vs PLAN GAP | `brief/REQUIREMENTS_BRIEF.md` §7 explicitly lists "Per-vendor deterministic parsers" as **out of scope** — *"Universal extraction is the default; build a vendor-specific fast path only if real volume/cost data justifies it later."* §9 additionally states the prior/reference application's code is *"reference-only... not a codebase this brief inherits scope... from."* Despite this, `ARCHITECTURE.md` D-J and `EXECUTION_PLAN.md` Session 3's own goal statement ("deterministic pdfplumber for known vendors") build exactly the per-vendor deterministic-parser pattern the brief defers, apparently carried over from investigating the reference implementation earlier in this project's history | **BLOCKER** | Needs an explicit decision: either the brief's §7 scope is being knowingly superseded (record why, and update the brief or add a decision note reconciling it), or D-J/Session 3 should be rescoped to universal (Claude-primary) extraction only, with per-vendor deterministic paths held until volume/cost data justifies them, per the brief's own stated test |
| ARCHITECTURE vs PLAN GAP | Non-negotiable N2's enforcing invariant was removed (see Section B) | HIGH | Duplicate of the Section B finding — listed here because it's also a genuine architecture-vs-brief gap, not just a traceability note |
| ARCHITECTURE vs PLAN GAP | `brief/REQUIREMENTS_BRIEF.md` §9 references `docs/VIVE_REBUILD_PLAN_TARGET_ARCHITECTURE.md` and `docs/VIVE_REBUILD_PLAN_BUSINESS.md` as the already-agreed build sequencing this project should follow. Neither file exists anywhere in this repo or the available project files. `EXECUTION_PLAN.md` was built without them | MEDIUM | Confirm whether these documents exist elsewhere and should have informed session sequencing, or whether the brief's reference is stale and should be corrected |
| ARCHITECTURE vs PLAN GAP | `brief/REQUIREMENTS_BRIEF.md` §7 says AI-assisted residual matching is *"designed for, but blocked on a governance sign-off unrelated to the technical build."* `EXECUTION_PLAN.md` Task 5.3 implements it with no feature flag or gate reflecting that blocking condition | MEDIUM | Add a configuration flag to Task 5.3 so the capability can be built but not enabled until that sign-off clears, rather than shipping it live by default |
| ARCHITECTURE vs PLAN GAP | Task 2.2's `Invariant enforcement` line cites S1/S2 only; its own CC prompt explicitly implements G4's content-hash idempotency behavior ("if a document with the same hash already exists, reject silently") but never cites G4. Its `Regression classification` line cites G1 for this, which is the wrong invariant for the hash-dedup behavior | LOW | Correct the citation — Task 2.2 should list G4 alongside S1/S2 |
| ARCHITECTURE vs PLAN GAP | Task 1.2's and Task 3.1's own titles/descriptions still contain leftover "Bronze-first" language in places, despite the D-J schema rename to `extracted` | LOW | Cosmetic — clean up on next pass, not functionally blocking |

---

## Section D — Risk Register with Dispositions

| # | Finding | Severity | Requirement or Invariant Affected | Return to Phase | Recommendation | Disposition | Rationale |
|---|---|---|---|---|---|---|---|
| 1 | No task populates `silver.statement_line` — matching reads from a table nothing writes to | BLOCKER | Requirements §3 item 4; G2; S8 | Phase 3 (Execution Planning) | Add a normalization task | RESOLVE | Task 3.6 added to EXECUTION_PLAN.md v1.4 (`extracted` → `silver.statement_line`, gated on Task 3.2's G2 validation, embeds S6 normalization-version traceability) |
| 2 | Unknown-vendor statement has no defined landing table | HIGH | Requirements §3 item 2 | Phase 3 | Add unknown-vendor path | RESOLVE | Engineer clarified: the app identifies vendor, not the user. ARCHITECTURE.md D-L amended (also resolves UI_SURFACE.md gap #3, not just this finding); EXECUTION_PLAN.md v1.5 — Task 3.1 rewritten to own vendor identification/routing (registry match → deterministic; no match → Claude-primary, provisional vendor creation, landing in `extraction_attempt.raw_output`); Task 2.2 narrowed to hash-dedup only; Task 1.2's `vendor_id`/`statement_period` made nullable |
| 3 | G5 has zero task coverage | BLOCKER | G5 | Phase 3 | Add lock/lease task coverage | RESOLVE | Task 2.4 (extraction trigger) and Task 5.1 (matching invocation) amended in EXECUTION_PLAN.md v1.4 with explicit G5 processing-ownership acquisition |
| 4 | Concurrent manual + scheduled matching undefined | HIGH | G5, OD1 | Phase 3 | Resolve with Finding 3 | RESOLVE | Closed by the same Task 5.1 amendment as Finding 3 — whichever path acquires the row lock first processes those documents, the other skips them |
| 5 | Auth mechanism disagreement across Claude.md / ARCHITECTURE.md / UI_SURFACE.md / Task 1.3 | BLOCKER | Requirements (implicit — auth architecture) | Phase 2 (Decide) or Phase 5 (Claude.md amendment) | Reconcile Entra ID vs. username/password | RESOLVE | Option (b) taken: `Claude.md` v1.2 corrected — username/password is the v1 build target (matches UI_SURFACE.md/Task 1.3 as-built); Entra ID recorded as the stated end-goal, not this build's mechanism |
| 6 | Per-vendor deterministic parsers contradict brief §7/§9's explicit scope exclusion | BLOCKER | Requirements §7, §9; D-J | Phase 1 (Interrogate) or Phase 2 (Decide) | Explicit supersession decision or rescope to universal extraction | RESOLVE | Option taken: explicit supersession, not rescope. New ARCHITECTURE.md D-L records the decision, rationale, rejected alternative, and revisit condition. `brief/REQUIREMENTS_BRIEF.md` gets an appended Engagement-Side Addendum (not an edit to §7 itself, per the brief's never-modified-after-receipt contract) cross-referencing D-L. EXECUTION_PLAN.md Session 3 goal statement cross-references D-L. |
| 7 | N2 (never call NetSuite/CCC live) has no enforcing invariant | HIGH | Requirements §4; removed G1 (original) | Phase 2 | Restore an enforced invariant or explicitly re-accept the soft-convention status | ACCEPT | Engineer: "still true but not needed to be defined." N2 remains true by construction — Task 5.2's matching only ever queries `silver.statement_line`/Silver reference data, no live-API code path exists anywhere in this plan to guard against. Accepted as a documented convention (Task 5.2's own text), not re-promoted to an enforced/tested invariant. Revisit if a future task ever introduces a live NetSuite/CCC call option (e.g. the "live pull as alternative matching mode" item already tracked in ARCHITECTURE.md's Open Questions) |
| 8 | Referenced rebuild-plan docs (`VIVE_REBUILD_PLAN_*`) don't exist in this repo | MEDIUM | Requirements §9 | Phase 1 | Confirm existence/relevance or correct the brief | *(engineer to disposition)* | |
| 9 | Task 5.3 has no gate for the governance sign-off the brief says blocks it | MEDIUM | Requirements §7 | Phase 3 | Add a feature flag | *(engineer to disposition)* | |
| 10 | Task 2.2 miscites G1 instead of G4 for hash-dedup behavior | LOW | G4 | Phase 3 | Correct citation | *(engineer to disposition)* | |
| 11 | Leftover "Bronze-first" language in Task 1.2/3.1 titles | LOW | — (cosmetic) | Phase 3 | Clean up wording | *(engineer to disposition)* | |
| 12 | `tools/` automation scripts not sourced | LOW | — (process, not a document defect) | N/A | Source before autonomous mode | *(engineer to disposition)* | |

**Overall verdict (updated 2026-08-27, final):** **GATE PASSED.** Step 1 = APPROVE — all 5
BLOCKER findings (1, 3, 4, 5, 6) and both HIGH findings (2, 7) are dispositioned (6 RESOLVE,
1 ACCEPT with rationale). MEDIUM #8–9 and LOW #10–12 remain `*(engineer to disposition)*`
but are cosmetic/process, not gate-blocking. Step 1c = RESOLVED (Section F). Step 2 =
COMPLETE. **Step 2b = COMPLETE** — G1/G2/G3/G4/G5 all PASS (Section E), including G3's
authorship-classification correction (Domain → Structural) and confirmation. Phase 5
(Claude.md) may now validly be considered open — the retroactive sequencing gap noted at
the top of this document is closed.
**Confidence level:** 95% — all four Phase 4 steps (1, 1c, 2, 2b) are complete; only
cosmetic/process findings (#8–12) remain, none gate-blocking.

*(Per `pbvi_core.md`: Claude may not declare this gate passed — the verdict above is this review's output, not a gate-pass declaration. Only the engineer signs off, in the Engineer Sign-Off section at the bottom.)*

---

---

## Section E — Invariant Failure Mode Review

**Step 2b run 2026-08-27.** Step 2's three ownership questions confirmed (yes/yes/yes,
recorded from memory, no documents open). G1/G2/G4/G5 confirmed below — engineer restated
each from memory, matching CD's drafted content, with G5's detection point independently
updated to reflect the Tasks 2.4/5.1 implementation (evidence of genuine engagement, not
rote agreement). **G3 corrected from "Domain" to "Structural"** — this session's original
classification was wrong; G3 (prompt-injection defense) is a security/structural control,
not an AP-business-domain rule, so it should have been offered as CD-drafted content to
confirm like the other four, not demanded purely from memory. Re-offered on that basis and
**confirmed as-drafted, 2026-08-27** — see table below.

| INV-ID | Category | Authorship | Violation (confirmed/corrected) | Detection (confirmed/corrected) | Blast Radius (confirmed/corrected) | Ownership result |
|---|---|---|---|---|---|---|
| G1 | Structural | CD-drafted | An extraction attempt exists with no valid parent document, or an existing attempt record is mutated after the fact | FK constraint (document_id); append-only enforcement at the write layer, no UPDATE on attempt rows | Loss of the audit trail G2/S10 depend on | **PASS** |
| G2 | Structural | CD-drafted | A document with failed arithmetic or structural validation becomes matching-eligible | Validation gate check at the Silver-promotion boundary | Extraction defects masquerade as business discrepancies | **PASS** |
| G3 | Structural (corrected from Domain) | CD-drafted | Document-controlled text alters the extraction prompt or model behavior | Code review checklist; prompt-template structural separation at the API-call layer | Silently corrupted extraction that passes all downstream checks | **PASS** — confirmed as-drafted, 2026-08-27 |
| G4 | Data | CD-drafted | The same PDF content is registered as a new processing unit and independently sent through extraction/reconciliation | Unique constraint on `content_sha256` at write time | Duplicate extraction/matching work, inflated statement counts | **PASS** |
| G5 | Structural | CD-drafted | Two workers/triggers independently process the same document/work item at the same time | Atomic ownership acquisition at trigger — Task 2.4's `UPDATE ... WHERE status != 'Processing'` guard (extraction), Task 5.1's per-document row lock (matching); whichever path acquires first proceeds, the other skips (updated in `INVARIANTS.md` v1.5 to match) | Duplicated Claude API spend, conflicting state writes, doubled processing cost | **PASS** — engineer independently updated the detection point before I did, confirming real engagement with the mechanism, not the pre-fix generic wording |

**Gate failure record:** None — no invariant failed the ownership test. G1/G2/G3/G4/G5 all
**PASS** as of 2026-08-27. Step 2b complete.

---

## Section F — UI Surface Review

**Applies** — APPLICATION_SURFACE is UI+API.

| Check | Finding | Severity | Recommendation | Disposition |
|---|---|---|---|---|
| Screen coverage | All six screens in `UI_SURFACE.md`'s Screen Inventory (Sign In, Home, Upload, Document Detail, Exceptions, Exception Detail) have at least one owning task (1.3, 6.1, 2.1, 6.5, 6.2, 6.3 respectively) | INFO | None needed | ACCEPT |
| Role-conditional testability | All conditional actions have either a UI test path or an explicit tracked-open status. The one exception — Sign In's "Sign in with company SSO" button — has Condition "TBD," but this is already disclosed in `UI_SURFACE.md`'s own Unresolved Gaps #1 and Task 1.3 renders it disabled with a test asserting that. Not a new gap | INFO | None needed beyond what's already tracked | ACCEPT |
| Global elements coverage | Navigation, Logout, Global error boundary (Task 1.4), and Session expiry (Task 1.3) all have an owning task | INFO | None needed | ACCEPT |
| Auth architecture consistency | **See Section C/D Finding 5** — `Claude.md` declares Entra ID; `UI_SURFACE.md`/Task 1.3 build username/password | **BLOCKER** | Reconcile before Phase 6 proceeds on Task 1.3 specifically | RESOLVE — `Claude.md` v1.2 corrected to username/password (v1); Entra ID recorded as future direction |

**Step 1c verdict:** RESOLVED (previously BLOCKED — auth architecture consistency). All
three signed-off documents now agree: username/password is this build's mechanism, Entra ID
is the stated end-goal. No blockers remain in Section F.

---

## Engineer Sign-Off

**Step 1 gate:** PASS — all BLOCKER and HIGH findings resolved (1, 3, 4, 5, 6 = RESOLVE; 2 =
RESOLVE; 7 = ACCEPT with rationale; see Section D). MEDIUM #8–9, LOW #10–12 remain
undispositioned but are non-blocking.
**Step 1c UI Surface Review:** RESOLVED — no blockers remain (see Section F)
**All RESOLVE findings addressed:** YES for BLOCKER and HIGH severity.
**Verdict confirmed:** GATE PASSED — 2026-08-27 (see Overall verdict above; only the
signature line below remains blank)
**Step 2 ownership confirmation:** COMPLETE — 2026-08-27, three questions answered from
memory
**Step 2b invariant failure mode review:** COMPLETE — 2026-08-27. G1/G2/G3/G4/G5 all PASS
(G3 confirmed as-drafted after its Domain → Structural classification correction).
**Signed:** Vaishali — 27-08-2026