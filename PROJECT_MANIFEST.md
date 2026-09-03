# PROJECT_MANIFEST.md — VIVE Statement Reconciliation

**METHODOLOGY_VERSION:** v4.9 (`pbvi_core.md`, PBVI-011 — UI as a First-Class Citizen)
**ONBOARDING_SOURCE:** Greenfield — PBVI Phase 1–5 (not brownfield; this is a fresh build,
not derived from any existing codebase)
**PROJECT_INITIALISED:** 2026-08-27
**PROFILE:** WEB_APPLICATION (permits `docs/UI_SPEC.md`, `docs/ROUTE_MAP.md` in addition
to the mandatory PBVI set — neither produced yet as of initialisation)
**APPLICATION_SURFACE:** UI+API — Session 1 includes Playwright scaffolding per PBVI-011
**INVARIANT_AUTHORSHIP_MODE:** GOVERNED (engineer drafted first, CD challenged and merged
— per `docs/INVARIANTS.md` v1.3's own authorship-mode note)
**DATA_BASELINE:** Migrated only — no Seeded component. `docs/SEED_DATA.md` correctly
skipped per the PBVI-011 conditional.

---

## ⚠ Known Prior Art (not incorporated into this build — recorded for traceability)

A separate, already-governed VIVE Reconciliation implementation exists (brownfield-onboarded
2026-07-24, `docs/Claude.md` at v2.9 as of 2026-08-06, Sprint Lead Ayush Kumar Sinha,
SPRINT-001 closed, 14-item enhancement backlog). This fresh build is a deliberate,
engineer-confirmed decision **not** to continue that repository or reuse its code,
invariant history, or calibration data. Anyone picking up this project later should know
that decision was made knowingly, not by omission — see chat history 2026-08-27 for the
full reasoning and trade-offs discussed before this choice was made.

---

## File Registry

| Path | Type | Status | Notes |
|---|---|---|---|
| `README.md` | Repo root | PRESENT | Navigation/orientation |
| `PROJECT_MANIFEST.md` | Repo root | PRESENT | This file |
| `Claude.md` | Repo root | PRESENT | Tool-compatibility shim — not authoritative content, per Location and Root Stub Pattern |
| `docs/Claude.md` | PBVI trunk artifact | PRESENT | v1.3 — Section 1 amended to match ARCHITECTURE.md D-A (lightweight exception-resolution workflow, short of the full deferred review/approval workspace); Section 4 corrected (Claude Sonnet 5, not 4.6), `frozen: true` |
| `docs/ARCHITECTURE.md` | PBVI trunk artifact | PRESENT | v1.6 — D-I amended (auto-extract-on-upload); D-A/Section-1-equivalent amended (exception-resolution workflow added); D-M extended (vendorcredit table, vendor-scoped matching, full raw-row capture); D-F resolution note (Legal Entity picker removed) |
| `docs/INVARIANTS.md` | PBVI trunk artifact | PRESENT | v1.7 — new OD6 (whether the exception-resolution workflow needs its own invariant, unresolved); G1–G5/S1–S11/T1–T7 reviewed against Session 6→9 work, confirmed unchanged |
| `docs/EXECUTION_PLAN.md` | PBVI trunk artifact | PRESENT | v1.8 — Tasks 2.1, 2.3, 2.4, 5.2, 6.1, 6.5 amended; Tasks 6.2/6.3 rewritten wholesale (vendor-grouped two-pane Exceptions architecture replacing the flat list); Session 8 (extraction quality) and Session 9 (per-vendor deterministic parsers + real OCR) tasks added |
| `docs/UI_SURFACE.md` | Dual-registered planning + discovery artifact (PBVI-011) | PRESENT | v1.5 — Exceptions/Exception Detail rewritten (vendor-grouped two-pane, replacing separate List/Detail screens); Home softened-status display; Upload Legal Entity field removed |
| `docs/PHASE4_GATE_RECORD.md` | PBVI trunk artifact (Phase 4 Design Gate) | PRESENT | **GATE PASSED AND SIGNED, 2026-08-27** — Vaishali. Step 1 = APPROVE (all 5 BLOCKERs, both HIGH findings dispositioned), Step 1c = RESOLVED, Step 2 = COMPLETE, Step 2b = COMPLETE (G1–G5 all PASS, including G3's Domain→Structural reclassification and confirmation). MEDIUM 8/9, LOW 10-12 remain open but non-blocking. |
| `docs/target-architecture/VIVE_Statement_Reconciliation_Architecture_v3_3.md` | Reference/target-state architecture | PRESENT | Full v3.3 target design this bounded build scopes down from |
| `brief/REQUIREMENTS_BRIEF.md` | Client input | PRESENT | Original content never modified after receipt, per directory contract. **Engagement-Side Addendum appended 2026-08-27** (not an edit to the original) recording §7's explicit supersession — see ARCHITECTURE.md D-L |
| `brief/Reconciliation_Engine_Reusable_Components.docx` | Client input | PRESENT | Reusable-components requirements brief — informs future ENH scoping, not yet incorporated into `docs/ARCHITECTURE.md`'s core/adapter boundary (see Open Questions) |
| `docs/prompts/` | CC execution prompts | PENDING | Not yet populated — created at Phase 6 session start |
| `sessions/` | Session logs + verification records | PRESENT | Populated as Phase 6 sessions run. `S01_SESSION_LOG.md` + `S01_VERIFICATION_RECORD.md` scaffolded 2026-08-27 on `session/s01_scaffolding-auth-db`. |
| `docs/EXECUTION_PLAN.md` — "LIGHTWEIGHT_PATCHES_LOG.md — Session 6 → Session 8 Gap" section | Embedded retrospective (not a standalone file — corrected 2026-09-01; the registry previously named this `sessions/LIGHTWEIGHT_PATCHES_LOG_S06_TO_S08.md`, which does not exist) | PRESENT | Retrospective, not a real-time log — covers the engineer-directed lightweight-patch work (Fabric live connectivity, matching bug fixes, Home/Upload/Exceptions UI redesigns) done between Session 6's completion and Session 8's start, with no task numbers of its own at the time. Written 2026-09-01 on request, after the fact; lives inside `docs/EXECUTION_PLAN.md` rather than `sessions/`. |
| `sessions/S08_SESSION_LOG.md` | Session logs + verification records | PRESENT | Session 8 — Extraction Quality Improvements (Tasks 8.1–8.5). Written retrospectively 2026-09-01 — this session ran in lightweight-patch mode (implement + live-data verify + commit), not full scaffold/challenge-agent ceremony; the log records that explicitly rather than reconstructing ceremony that didn't happen. |
| `sessions/S08_VERIFICATION_RECORD.md` | Session logs + verification records | PRESENT | Verification method: live extraction against real vendor statement PDFs, arithmetic reconciliation confirmed to the cent, full Playwright suite — not a Challenge Agent adversarial review (none was run for this session; recorded honestly, not fabricated). |
| `sessions/S09_SESSION_LOG.md` | Session logs + verification records | PRESENT | Session 9 — Per-Vendor Deterministic Parsers + Real OCR (Tasks 9.1–9.6 completed; former 9.7 "OCR-derived parsers" removed 2026-09-01, premise didn't hold; 9.8 renumbered to 9.7, completed). Includes the `ensureVendorStmtTable` bug found and fixed mid-session. Same lightweight-patch mode as Session 8. |
| `sessions/S09_VERIFICATION_RECORD.md` | Session logs + verification records | PRESENT | Same verification method as S08 — live reconciliation against real PDFs (9 vendors, exact arithmetic match), full pipeline re-verification after the `ensureVendorStmtTable` fix, full Playwright suite. No Challenge Agent review run. |
| `verification/` | Sign-off checklists | PRESENT | Populated 2026-09-01 for Phase 8 Part 1 (System Sign-Off): `REGRESSION_SUITE.sh`, `HARNESS.sh`, `UI_HARNESS.sh` (all assembled per PBVI Template 9 / PBVI-011 and actually run against the local SQLite fallback — real results, not scaffolding), and `VERIFICATION_CHECKLIST.md` (Session Completion, Invariant Validation, Architecture Alignment, Operational Readiness all populated with real evidence; Final Sign-Off left blank for engineer — CC cannot self-sign). One real invariant gap found (S7 status-badge display) and one verification-tooling gap found (fixture scripts not safe to re-run against a used local DB) — both recorded in the checklist, neither silently fixed. |
| `discovery/` | BCE SIL artifacts | PENDING | Not yet applicable — produced at Phase 8 |
| `enhancements/REGISTRY.md` | Enhancement registry | PRESENT | Created 2026-09-03 at Sprint CC Initiation for SPRINT-001 — this project's first post-Phase-8 enhancement |
| `enhancements/SPRINT-001/` | Sprint container | PRESENT | Created 2026-09-03. Contains `SPRINT-001_LOG.md` (open), `SPRINT-001_MANIFEST.md` (placeholder, pending Prompt 2), and `ENH-001-ui-clarity-multi-pdf-upload/` package |
| `enhancements/backlog/INVARIANT-DRIFT-001/` | INVARIANT-DRIFT item | PRESENT | Created 2026-09-03 — `verification/HARNESS.sh` S7 assertion (`test_bounded_retry.sh`) failed at Sprint CC Initiation. **DISMISSED** by Sprint Lead (Vaishali, 2026-09-03): BCE evidence (`discovery/INVARIANT_CATALOGUE.md` S7 entry) already root-caused this as a stale test literal, not a real regression. Harness maintenance task recorded in `SPRINT-001_LOG.md` Event Log, not yet actioned |
| `enhancements/SPRINT-001/ENH-001-ui-clarity-multi-pdf-upload/S1_execution_prompt.md` | Phase 5 session prompt file | PRESENT | Produced 2026-09-03. Corrected a stale Claude.md version reference (said v1.3, actual v1.4) 2026-09-03 |
| `enhancements/SPRINT-001/ENH-001-ui-clarity-multi-pdf-upload/S2_execution_prompt.md` | Phase 5 session prompt file | PRESENT | Produced 2026-09-03. Same v1.3→v1.4 correction applied |
| `enhancements/FEATURE_STATUS.md` | Informal cross-project status snapshot (not a PBVI-governed artifact) | PRESENT | Created 2026-09-03. Human-facing reference only — not treated as authoritative build input per Claude.md Rule 3 |
| `tools/` | Agentic build scripts | PRESENT | Five standard DG-Forge automation scripts (`challenge.sh`, `resume_challenge.sh`, `resume_session.sh`, `monitor.sh`, `launch.sh`) sourced 2026-08-27 from the local `dg-os` repository ahead of Session 1, per `pbvi_core.md`'s Directory Creation convention. |
| `.claude/SKILL.md` | DG-Forge methodology reference (PBVI, monolithic pre-split) | PRESENT | Copied 2026-08-27 from `dg-os/skills/PBVI/SKILL.md` per `pbvi_build.md`'s Phase 6 setup requirement. Frontmatter version v4.9 — matches this project's declared METHODOLOGY_VERSION exactly (dg-os's current default is the split v5.0 pbvi_core.md/pbvi_build.md/pbvi_plan.md; this older monolithic copy was selected instead to avoid a version mismatch). Never edited locally — refresh from DG-Forge source on explicit migration only. |
| `ui_tests/` | Non-standard registered directory — Playwright UI test specs | PRESENT | Registered 2026-08-27 per Task 1.1 (EXECUTION_PLAN.md Session 1). Phase: Phase 6. Owner: CC. One spec file per screen/flow, per each task's UI test spec. |

---

## Open Items Before Phase 6 (Build) Can Begin

1. ~~**Phase 4 Design Gate**~~ — **PASSED AND SIGNED, 2026-08-27** (Vaishali). All four
   steps complete: Step 1 (APPROVE — all 5 BLOCKERs and both HIGH findings dispositioned),
   Step 1c (RESOLVED), Step 2 (COMPLETE), Step 2b (COMPLETE — G1–G5 all PASS). See
   `docs/PHASE4_GATE_RECORD.md`'s Overall verdict and Engineer Sign-Off. Phase 5 (Claude.md)
   is validly open; the retroactive-sequencing gap noted at the top of the gate record is
   closed.
2. ~~**`tools/` scripts**~~ — **RESOLVED 2026-08-27.** Sourced from the local `dg-os`
   repository ahead of Session 1 (see File Registry above). Session 1 runs in Autonomous
   mode, so this was a hard prerequisite, not just a soft blocker.
3. **Reusable-components boundary — partially addressed, by design (2026-08-27).** D-K
   applied two narrow reconciliations from `brief/Reconciliation_Engine_Reusable_
   Components.docx`: `extracted.document.artifact_type` and a structured pipeline result
   contract (Tasks 3.2, 5.2, 5.3, 5.4). **Deliberately still unaddressed, per that brief's
   own deferral to BCE (unchanged):** Run Manager, generic Document Registry service,
   Audit Ledger, Human Review Contract. **Genuinely open, no decision made either way:**
   Evaluation Harness, Observability/correlation package — neither Build1 nor BCE has
   claimed these yet. Not a Phase 6 blocker.

**Net: Phase 6 (Build) can begin.** Item 1 is resolved. Item 2 only matters for
automated/autonomous build sessions — manually-driven Session 1 is unaffected. Item 3 is
not a blocker.
