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
| `docs/Claude.md` | PBVI trunk artifact | PRESENT | v1.1 — DRAFT, pending sign-off (see flagged items in changelog) |
| `docs/ARCHITECTURE.md` | PBVI trunk artifact | PRESENT | v1.3 — DRAFT, pending sign-off |
| `docs/INVARIANTS.md` | PBVI trunk artifact | PRESENT | v1.4 — DRAFT, pending sign-off |
| `docs/EXECUTION_PLAN.md` | PBVI trunk artifact | PRESENT | v1.3 — DRAFT, not yet frozen (Phase 8 pending) |
| `docs/UI_SURFACE.md` | Dual-registered planning + discovery artifact (PBVI-011) | PRESENT | v1.2 — DRAFT, pending sign-off |
| `docs/target-architecture/VIVE_Statement_Reconciliation_Architecture_v3_3.md` | Reference/target-state architecture | PRESENT | Full v3.3 target design this bounded build scopes down from |
| `brief/REQUIREMENTS_BRIEF.md` | Client input | PRESENT | Never modified after receipt, per directory contract |
| `brief/Reconciliation_Engine_Reusable_Components.docx` | Client input | PRESENT | Reusable-components requirements brief — informs future ENH scoping, not yet incorporated into `docs/ARCHITECTURE.md`'s core/adapter boundary (see Open Questions) |
| `docs/prompts/` | CC execution prompts | PENDING | Not yet populated — created at Phase 6 session start |
| `sessions/` | Session logs + verification records | PENDING | Populated as Phase 6 sessions run |
| `verification/` | Sign-off checklists | PENDING | Populated at Phase 4 gate and beyond |
| `discovery/` | BCE SIL artifacts | PENDING | Not yet applicable — produced at Phase 8 |
| `enhancements/` | Enhancement registry | PENDING | Empty until first post-Phase-8 enhancement |
| `tools/` | Agentic build scripts | **PENDING — see note** | The five standard DG-Forge automation scripts (`challenge.sh`, `resume_challenge.sh`, `resume_session.sh`, `monitor.sh`, `launch.sh`) have not been pulled in yet — source them from the DG-Forge repository before Phase 6 begins, per `pbvi_core.md`'s Directory Creation convention. Not fabricated here since this project has no access to that source. |

---

## Open Items Before Phase 6 (Build) Can Begin

1. **Phase 4 Design Gate sign-off** — four items across `docs/ARCHITECTURE.md` v1.3 and
   `docs/INVARIANTS.md` v1.4 remain unconfirmed: G2 confidence-floor removal, S2/OD4
   version-chaining without a human checkpoint, D-J's per-vendor `extracted` schema, and
   D-K's reusable-components reconciliation (lowest risk of the four, but new). `docs/
   Claude.md`'s `frozen: true` is provisional pending these.
2. **`tools/` scripts** — not yet sourced (see File Registry note above).
3. **Reusable-components boundary — partially addressed (2026-08-27).** D-K applied two
   narrow reconciliations from `brief/Reconciliation_Engine_Reusable_Components.docx`:
   `extracted.document.artifact_type` and a structured pipeline result contract
   (Tasks 3.2, 5.2, 5.3, 5.4). **Deliberately still unaddressed, per that brief's own
   deferral to BCE (unchanged):** Run Manager, generic Document Registry service, Audit
   Ledger, Human Review Contract. **Genuinely open, no decision made either way:**
   Evaluation Harness, Observability/correlation package — neither Build1 nor BCE has
   claimed these yet.
