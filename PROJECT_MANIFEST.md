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
| `docs/Claude.md` | PBVI trunk artifact | PRESENT | v1.2 — auth corrected (username/password v1, Entra ID = end-goal) per `docs/PHASE4_GATE_RECORD.md` Finding 5, `frozen: true` |
| `docs/ARCHITECTURE.md` | PBVI trunk artifact | PRESENT | v1.4 — D-L (§7 supersession) + vendor-identification amendment, D-H amendment (version-chaining timing), per `docs/PHASE4_GATE_RECORD.md` Findings 6 and 2 |
| `docs/INVARIANTS.md` | PBVI trunk artifact | PRESENT | v1.4 — **SIGNED OFF 2026-08-27** |
| `docs/EXECUTION_PLAN.md` | PBVI trunk artifact | PRESENT | v1.5 — Task 3.6 (Silver normalization), G5 lock/lease (2.4/5.1), Task 3.1 rewritten (vendor identification/routing, moved version-chaining), Task 2.2 narrowed to hash-dedup, per `docs/PHASE4_GATE_RECORD.md` Findings 1/2/3/4 (not FROZEN — that's a Phase 8 banner, separate from sign-off) |
| `docs/UI_SURFACE.md` | Dual-registered planning + discovery artifact (PBVI-011) | PRESENT | v1.3 — Vendor removed as Upload form field (gap #3 resolved), per `docs/PHASE4_GATE_RECORD.md` Finding 2 |
| `docs/PHASE4_GATE_RECORD.md` | PBVI trunk artifact (Phase 4 Design Gate) | PRESENT | **GATE PASSED AND SIGNED, 2026-08-27** — Vaishali. Step 1 = APPROVE (all 5 BLOCKERs, both HIGH findings dispositioned), Step 1c = RESOLVED, Step 2 = COMPLETE, Step 2b = COMPLETE (G1–G5 all PASS, including G3's Domain→Structural reclassification and confirmation). MEDIUM 8/9, LOW 10-12 remain open but non-blocking. |
| `docs/target-architecture/VIVE_Statement_Reconciliation_Architecture_v3_3.md` | Reference/target-state architecture | PRESENT | Full v3.3 target design this bounded build scopes down from |
| `brief/REQUIREMENTS_BRIEF.md` | Client input | PRESENT | Original content never modified after receipt, per directory contract. **Engagement-Side Addendum appended 2026-08-27** (not an edit to the original) recording §7's explicit supersession — see ARCHITECTURE.md D-L |
| `brief/Reconciliation_Engine_Reusable_Components.docx` | Client input | PRESENT | Reusable-components requirements brief — informs future ENH scoping, not yet incorporated into `docs/ARCHITECTURE.md`'s core/adapter boundary (see Open Questions) |
| `docs/prompts/` | CC execution prompts | PENDING | Not yet populated — created at Phase 6 session start |
| `sessions/` | Session logs + verification records | PENDING | Populated as Phase 6 sessions run |
| `verification/` | Sign-off checklists | PENDING | Populated at Phase 4 gate and beyond |
| `discovery/` | BCE SIL artifacts | PENDING | Not yet applicable — produced at Phase 8 |
| `enhancements/` | Enhancement registry | PENDING | Empty until first post-Phase-8 enhancement |
| `tools/` | Agentic build scripts | PRESENT | Five standard DG-Forge automation scripts (`challenge.sh`, `resume_challenge.sh`, `resume_session.sh`, `monitor.sh`, `launch.sh`) sourced 2026-08-27 from the local `dg-os` repository ahead of Session 1, per `pbvi_core.md`'s Directory Creation convention. |
| `.claude/SKILL.md` | DG-Forge methodology reference (PBVI, monolithic pre-split) | PRESENT | Copied 2026-08-27 from `dg-os/skills/PBVI/SKILL.md` per `pbvi_build.md`'s Phase 6 setup requirement. Frontmatter version v4.9 — matches this project's declared METHODOLOGY_VERSION exactly (dg-os's current default is the split v5.0 pbvi_core.md/pbvi_build.md/pbvi_plan.md; this older monolithic copy was selected instead to avoid a version mismatch). Never edited locally — refresh from DG-Forge source on explicit migration only. |

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
