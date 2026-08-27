---
name: pbvi-core
version: v4.9
description: >
  PBVI core skill — Phases 1 through 8 for greenfield builds. Load for all planning
  work (Phases 1-5 in CD) and build work (Phases 6-8 in CC). Contains all phase
  prompts, session execution prompts, quick reference rules, and human accountability
  gates. For enhancement and sprint work also load pbvi_sprint.md. For templates load
  pbvi_templates.md. For BCE work load bce_core.md. For BCE-S signal extraction
  (Tier 3) also load bce_signal.md. PBVI-009: Brownfield Onboarding Procedure added
  for BCE-extracted systems entering PBVI for the first time. PBVI-010: Phase 6
  Pre-Build Validation added (Claude.md schema validation + CC interpretation
  confirmation before first task). Claude.md Schema reference section added.
  CQR-001: Conversation Quality Review — fires automatically at Phase 1–5 gate close
  in CD. Two-dimension rubric (Ownership, Dialogue), A/B/C/D grade, phase-specific
  observations, next-time coaching tips. Phase 1 weights Dialogue more heavily.
  Cannot be skipped. Does not apply to Phase 6–8 CC sessions.
  PBVI-011: UI as a First-Class Citizen. UI promoted to first-class methodology
  citizen across all eight phases. New artifacts UI_SURFACE.md (functional UI
  surface specification, dual-registered as planning + discovery artifact) and
  SEED_DATA.md (conditional on data baseline = Seeded). Phase 1 Interrogate gains
  Application Profile output (surface type, auth, roles, data baseline). Phase 1
  Decide gains UI Discovery sub-phase (three-pass prompt). Phase 2 Step 0
  restructured for UI projects. Phase 2 Step 1 UI checks updated to reference
  UI_SURFACE.md. Phase 3 gains per-task item 7 (UI test spec) and conditional
  seed script task. Phase 4 Design Gate gains Step 1c UI Surface Review. Phase 5
  Claude.md gains session-scoped UI Surface section. Phase 6 gains mandatory
  Playwright test writing for UI-touching tasks. Phase 8 gains step 9 —
  UI_HARNESS.sh assembly. APPLICATION_SURFACE field formalised in
  PROJECT_MANIFEST.md. BCE module classification extended with UI layer types
  (see bce_core.md v2.3).
OWNER: DataGrokr LLC
COPYRIGHT: "© 2025 DataGrokr LLC. All rights reserved."
LICENSE: >-
  Proprietary — for use by licensed DataGrokr clients only.
  Unauthorized reproduction, modification, or transfer is prohibited.
CONTACT: naveen@datagrokr.com
---

# PBVI Core Skill — v4.9

## Changelog

| Version | Date | Summary |
|---|---|---|
| v4.9 | May 2026 | PBVI-011 — UI as a First-Class Citizen. Comprehensive upgrade across all eight phases for projects where APPLICATION_SURFACE contains UI. New artifacts: UI_SURFACE.md (functional surface spec, dual-registered as planning and discovery artifact), SEED_DATA.md (conditional — data baseline = Seeded). New Phase 1 Interrogate output: Application Profile (surface type, auth, roles, data baseline). New Phase 1 Decide sub-phase: UI Discovery (Pass 0 global elements, Pass 1 screen inventory, Pass 2 per-screen functional spec). Phase 2 Step 0 restructured for UI projects (consistency check against UI_SURFACE.md). Phase 2 Step 1 UI checks updated to reference UI_SURFACE.md (four checks including conditional-action governance). Phase 4 Design Gate gains Step 1c UI Surface Review. Phase 3 gains per-task UI test specs (item 7) and conditional seed script task. Phase 5 Claude.md gains session-scoped UI Surface section. Phase 6 gains Playwright test writing as mandatory step for UI-touching tasks (step 3b). Phase 8 gains UI_HARNESS.sh assembly (step 9). BCE module classification extended with UI layer types (bce_core.md v2.3). APPLICATION_SURFACE field formalised in PROJECT_MANIFEST.md. Soft break — BREAKING_CHANGES.md entry registered. pbvi_templates.md v3.12. |
| v4.8 | April 2026 | CQR-001 — Conversation Quality Review introduced. Fires automatically at Phase 1–5 gate close in CD. Two-dimension rubric: Ownership and Dialogue. A/B/C/D grade with phase-specific observations and next-time coaching tips. Phase 1 weights Dialogue more heavily. Cannot be skipped. Does not apply to Phase 6–8 CC sessions. New "Conversation Quality Review" section added between Quick Reference and Where to Find Everything Else. Five gate trigger lines added — one per phase. Quick Reference rule added. |
| v4.7 | April 2026 | PBVI-010 — Phase 6 Pre-Build Validation. New named sub-step at the start of every build session — runs before the first task in autonomous and manual mode. Two checks: (A) Claude.md schema validation — five required sections present, CQ-001 complexity invariant present, METHODOLOGY_VERSION recorded, M-NNN/IC-N/IP-NNN reference resolution against ID_REGISTRY.md. HALT on any section missing, CQ-001 missing, or any stale/invalid ID; WARN on METHODOLOGY_VERSION mismatch only (FW-001); N-A graceful fallback when ID_REGISTRY.md absent (greenfield pre-Phase 8). (B) CC interpretation confirmation — CC produces three statements before first task: modules I will modify, invariants I will respect, blast radius (in scope, out of scope, integration points, entities). Engineer confirms or halts. HALT or -WRONG returns engineer to planning — no code written until CONFIRMED. New Claude.md Schema reference section added (adjacent to Phase 5). Session log gains Pre-Build Validation block. pbvi_templates.md v3.11. |
| v4.6 | April 2026 | PBVI-009 — Brownfield Onboarding Procedure. New named procedure (not a PBVI path) that derives the PBVI planning artifact set from a completed BCE artifact set. Five steps: BCE completeness check (with remediation paths for missing SYSTEM_GRAPH.json or DOMAIN_MODEL.json), ARCHITECTURE.md derivation as an interpretive document (not a BCE rehash; 1-3 page target), INVARIANTS.md dual-source derivation, Claude.md generation, sprint-ready declaration. Trigger phrases at step level only — no master invocation. Runs once per brownfield system. Produces docs/ARCHITECTURE.md, docs/INVARIANTS.md, Claude.md, PROJECT_MANIFEST.md (with ONBOARDING_SOURCE field), and discovery/ONBOARDING_LOG.md. Does NOT produce EXECUTION_PLAN.md, sessions/ content, HARNESS.sh, REGRESSION_SUITE.sh, or PHASE4_GATE_RECORD.md — these come from the first sprint. INVARIANT_AUTHORSHIP_MODE = GOVERNED (v4.5 brownfield default confirmed). ONBOARDING_LOG.md added as new BCE-adjacent attestation artifact. pbvi_templates.md v3.10. pbvi_sprint.md v1.4 (sprint entry precondition updated). |
| v4.5 | April 2026 | PBVI-008 — Greenfield Composed Sutton. Greenfield default authorship mode changed to ASSISTED. Three-category invariant model (Structural / Data / Domain): CD drafts structural and data invariants with Failure Mode Draft; engineer authors domain invariants. Failure Mode Draft (three-part: violation observable state, detection point, blast radius) embedded in INVARIANTS.md per invariant; serves as Phase 4 gate input and Phase 8 harness specification. Phase 4 Step 2 gains named Step 2b — Invariant Failure Mode Review: structured ownership test per invariant; gate failure returns invariant to Phase 2; Phase 5 does not open until all pass. INVARIANT_AUTHORSHIP_MODE field added to PROJECT_MANIFEST.md template (ASSISTED for greenfield, GOVERNED for brownfield; GOVERNED on greenfield requires written rationale). Revision rule relaxed: engineer must approve every revision, no longer author every word. pbvi_templates.md v3.9. BREAKING: Phase 2 Step 1 prompt changed — ASSISTED flow replaces engineer-draft-first for greenfield projects. |
| v4.4 | April 2026 | PBVI-007 — Live Invariant Harness. Phase 3 task format field 6 extended to three-value classification: NOT-REGRESSION-RELEVANT / REGRESSION-RELEVANT / HARNESS-CANDIDATE. HARNESS-CANDIDATE criteria: stateless, portable, executable against a running system without build context, directly tied to a named invariant in INVARIANTS.md. Phase 8 Part 1: step 8 added — harness assembly from all HARNESS-CANDIDATE tasks into verification/HARNESS.sh (Template 9, pbvi_templates.md v3.8); not optional, not deferred. Phase 8 completion criteria updated: HARNESS.sh added as required output. How to Invoke table: Run regression suite, Run harness check, and Assemble harness trigger phrases added. pbvi_templates.md v3.8. |
| v4.3 | April 2026 | PBVI-006 — PHASE4_RISK_DECISIONS.md renamed to docs/PHASE4_GATE_RECORD.md and re-scoped to capture all four Design Gate steps: evaluation criteria, requirements traceability, adversarial stress test findings, and risk register with RESOLVE/ACCEPT dispositions. Phase 4 save instruction updated. docs/PHASE4_GATE_RECORD.md added to PROJECT_MANIFEST.md Core Documents table. Template in pbvi_templates.md v3.7. bce_core.md v1.7 references updated. |
| v4.2 | April 2026 | FW-001 — Methodology version compatibility model introduced. METHODOLOGY_VERSION field added to PROJECT_MANIFEST.md initialisation scaffold — declared at project start, updated only on explicit migration. Version compatibility check added at phase gates: Phase 2, Phase 3, Phase 4, Phase 5. Each check reads METHODOLOGY_VERSION from PROJECT_MANIFEST.md, compares against skill frontmatter version, and outputs a named warning block if they differ — then continues without stopping. Warning directs engineer to BREAKING_CHANGES.md. Template 2B updated to v3.6: same version check added to REPOSITORY CONTEXT section for session-level detection. |
| v4.1 | April 2026 | CQ-002 — Automated regression suite introduced as a named Phase 8 output. Phase 3 task format extended with item 6: regression classification (REGRESSION-RELEVANT / NOT-REGRESSION-RELEVANT with one-line rationale); regression-relevant tasks carry a portability requirement on their verification commands; AI classifies at generation time, engineer confirms at sign-off. Phase 8 Part 1: step 7 added — regression suite assembly after system sign-off; collect portable verification commands from all REGRESSION-RELEVANT tasks, consolidate into verification/REGRESSION_SUITE.sh, commit to repo; non-portable commands noted with reason, not silently omitted; step is not optional and not deferred. Phase 8 completion criteria updated: regression suite committed to verification/REGRESSION_SUITE.sh is now a named required output. |
| v4.0 | April 2026 | CQ-001 — Cyclomatic complexity constraint introduced across three sites: (1) Phase 2 challenge checklist — complexity accumulation test added as sixth check, applied during invariant challenge to flag architecture-forced complexity accumulation. (2) Phase 5 Hard Invariants — methodology-mandated complexity invariant pre-declared in every Claude.md; does not consume an engineer slot; cannot be removed; text: "Each function, method, or handler must have a single stateable purpose. Conditional nesting exceeding two levels is a structural violation — refactor before proceeding. This is never negotiable." Reusable Phase 5 prompt updated to match. (3) Quick Reference — complexity rule added in same register as existing rules. PBVI Templates aligned to v3.5. |
| v3.9 | April 2026 | Session Execution Prompt moved to Template 2B (pbvi_templates.md v3.4) — skill section reduced from ~255 lines to a 10-line pointer. Session Log and Verification Record template sections removed — generation rules already in pbvi_templates.md Templates 1 and 2. Net reduction: ~275 lines from pbvi_core.md. |
| v3.8 | April 2026 | Two session execution prompts (Manual and Autonomous) rationalized into one unified Session Execution Prompt with mode-conditional steps inline. Manual mode gains all agentic discipline checks: File Boundary Check, Pre-Commit Declaration, Challenge Agent, Out of Scope Observations. |
| v3.7 | April 2026 | Wave 5 agentic build changes: tools/ directory added to Standard Repository Structure and project initialisation scaffold (PBVI-M-012). Session prompt file trigger phrase added to How to Invoke table; Phase 6 gate description strengthened (PBVI-M-001). |
| v3.6 | April 2026 | Wave 4 agentic build changes: Autonomous mode per-task step 8 replaced — self-challenge removed, independent challenge agent invocation added via ./tools/challenge.sh (PBVI-M-009). CHALLENGE FINDINGS handling block added to session execution prompt between FAILURE HANDLING and SCOPE VIOLATION HANDLING (PBVI-M-010). CHALLENGE FINDINGS summary output format defined. How to Invoke table: resume after challenge findings trigger phrase added. Quick Reference: challenge rule added (PBVI-M-009, PBVI-M-010). |
| v3.5 | April 2026 | Wave 3 agentic build changes: Autonomous mode per-task order extended to 13 steps — deterministic file boundary check via git diff --name-only (step 6), pre-commit declaration with self-certification (step 7), Out of Scope Observations recording (step 10), updated commit step (step 12) (PBVI-M-005, PBVI-M-006). Session execution prompt updated — FILE BOUNDARY CHECK, PRE-COMMIT DECLARATION, and SCOPE VIOLATION HANDLING blocks added to TASK-LEVEL VERIFICATION; SCOPE VIOLATION HANDLING section added between FAILURE HANDLING and HUMAN GATES (PBVI-M-005, PBVI-M-006, PBVI-M-008). Quick Reference: scope violation rule added (PBVI-M-008). |
| v3.4 | April 2026 | Wave 2 agentic build changes: Git commit format extended with mandatory scope declaration fields for Autonomous mode (PBVI-M-011). Task Prompt Immutability rule added to Autonomous mode description — exact-as-written execution, Out of Scope Observations as release valve (PBVI-M-004). Greenfield session prompt path convention added as named Phase 5 output — sessions/S[N]_execution_prompt.md, What Has Already Been Built paragraph requirement, trigger phrase and gate defined (PBVI-M-013). |
| v3.3 | April 2026 | Phase 3 gate updated — Tier reconfirmation step added for enhancements. CD now prompts engineer to confirm Sign-Off Tier before execution planning begins. References ENH-NNN_SCOPE.md Section 7 (Phase 3 Gate — Tier Reconfirmation). |

## How to Invoke Prompts

Say any of these phrases to invoke the corresponding prompt. Claude will load
the relevant context and run the prompt. Gates embedded in each prompt tell
Claude where to stop and wait for your input.

| What you want to do | Say this | Tool | Phase |
|---|---|---|---|
| Interrogate the requirements brief | "Interrogate the brief" / "Run Phase 1 Interrogate" | CD | 1 |
| Generate architecture options | "Explore architectures" / "Run Phase 1 Explore" | CD | 1 |
| Produce ARCHITECTURE.md | "Produce ARCHITECTURE.md" / "Document my architecture decision" | CD | 1 |
| Map data touch points | "Map data touch points" / "Run Phase 2 Step 0" | CD | 2 |
| Draft invariants for this system (ASSISTED) | "Draft invariants for this system" / "Help me define invariants" | CD | 2 |
| Challenge my invariants (GOVERNED) | "Challenge my invariants" / "Review my invariant draft" | CD | 2 |
| Help me define domain invariants | "Help me define domain invariants" | CD | 2 |
| Check invariant sufficiency | "Run sufficiency check" / "Check invariants against architecture" | CD | 2 |
| Produce INVARIANTS.md | "Produce INVARIANTS.md" | CD | 2 |
| Produce the execution plan | "Produce the execution plan" / "Run Phase 3" | CD | 3 |
| Run the Design Gate review | "Run Design Gate" / "Run Phase 4" | CD | 4 |
| Produce Claude.md | "Produce Claude.md" / "Create the execution contract" | CD | 5 |
| Start a manual build session | "Start manual session [N]" | CC | 6 |
| Start an autonomous build session | "Run session [N] autonomously" | CC | 6 |
| Resume after a BLOCKED stop | "Resume session [N] from task [ID]" | CC | 6 |
| Resume after CHALLENGE FINDINGS | "Resume after challenge findings session [N] task [ID]" | CC | 6 |
| Session context getting too long | "Give me a handoff prompt" | CD | 6 |
| Produce session prompt files | "Produce session prompt files for this project" | CD | 5 |
| Migrate a project to PBVI structure | "Help me migrate this project" | CC | — |
| Migrate INVARIANTS.md to v3.0 (scope split) | "Migrate INVARIANTS.md to v3.0" / "Add scope classification to invariants" | CD then CC | — |
| Migrate EXECUTION_PLAN.md to v4.1 (regression) | "Migrate EXECUTION_PLAN.md to v4.1" / "Add regression classification to tasks" | CD then CC | — |
| Migrate design gate record to v4.3 | "Migrate PHASE4_RISK_DECISIONS.md to v4.3" / "Migrate design gate record to v4.3" | CC | — |
| Migrate INVARIANTS.md to v4.5 (PBVI-008) | "Migrate INVARIANTS.md to v4.5" / "Add failure mode fields to invariants" | CD then CC | — |
| Run regression suite on demand | "Run regression suite" | CC | 8 |
| Run harness check on demand | "Run harness check" | CC | 8 |
| Assemble live invariant harness | "Assemble harness" | CC | 8 |
| Run BCE completeness check (brownfield onboarding step 1) | "Run Step 1 of brownfield onboarding" · "Run BCE completeness check for brownfield onboarding" | CD | — |
| Derive ARCHITECTURE.md (brownfield onboarding step 2) | "Run Step 2 of brownfield onboarding" · "Derive ARCHITECTURE.md for brownfield onboarding" | CD | — |
| Derive INVARIANTS.md (brownfield onboarding step 3) | "Run Step 3 of brownfield onboarding" · "Derive INVARIANTS.md for brownfield onboarding" | CD | — |
| Generate Claude.md (brownfield onboarding step 4) | "Run Step 4 of brownfield onboarding" · "Generate Claude.md for brownfield onboarding" | CD | — |
| Sprint-ready declaration (brownfield onboarding step 5) | "Run Step 5 of brownfield onboarding" · "Declare system sprint-ready" | CD | — |
| Phase 6 Pre-Build Validation | Automatic at every build session start — no engineer trigger | CC | 6 |
| Run UI Discovery (PBVI-011) | "Run UI Discovery" / "Produce UI_SURFACE.md" / "Run Phase 1 UI Discovery" | CD | 1 |
| Run UI Design Gate review (PBVI-011) | "Run UI Design Gate" | CD | 4 |
| Assemble UI harness (PBVI-011) | "Assemble UI harness" | CC | 8 |
| Run UI harness (PBVI-011) | "Run UI harness" | CC | 8 |

---

## Eight-Phase Overview

| Phase | Name | PBVI Stage | Key Output | Human Gate |
|---|---|---|---|---|
| 1 | Discovery and Architecture | PLAN | ARCHITECTURE.md | Engineer owns the problem — can state it without AI assistance |
| 2 | Invariant Definition | PLAN | INVARIANTS.md + Failure Mode Draft | ASSISTED (greenfield default): CD drafts structural/data invariants, engineer authors domain invariants, engineer signs off all. GOVERNED (brownfield): engineer authors first, signs off final set. |
| 3 | Execution Planning | PLAN | EXECUTION_PLAN.md | All open questions resolved before plan is produced |
| 4 | Design Gate | PLAN | Risk Register | Structured review passed and all Critical/High findings resolved; engineer answers three gate questions without opening any document |
| 5 | Claude.md Creation | PLAN | Claude.md (FROZEN) | Phase 4 gate must pass before this phase begins |
| 6 | Build | BUILD | Code, per-session SESSION_LOG.md + VERIFICATION_RECORD.md | Scaffold commit before first CC prompt; one task = one commit |
| 7 | Session Integration Check | VERIFY | VERIFICATION_RECORD.md complete | Engineer signs off each session before PR is raised |
| 8 | System Sign-Off | INTEGRATE | VERIFICATION_CHECKLIST.md + discovery/ artifacts (greenfield) / ENH-NNN_BCE_IMPACT.md (enhancement — see pbvi_sprint.md Part 2B) | All invariants verified end-to-end; BCE adapter pipeline complete; documented sign-off required |

> **Phase 8 — greenfield vs. enhancement:** The Key Output above differs by build type. Greenfield (Part 2A): building engineer produces all seven discovery/ artifacts directly. Enhancement (Part 2B): building engineer produces ENH-NNN_BCE_IMPACT.md only — discovery/ artifact updates are deferred to sprint close-out by the Sprint Lead. See the Phase 8 section below and pbvi_sprint.md Part 2B.

Phases build sequentially. The loop is not a failure state — it is the mechanism that keeps planning honest. Two things trigger a return to an earlier phase:

Build-time failure: a verification failure during Phase 6 or 7 that invalidates a planning assumption — return to the phase that produced the broken assumption.

Planning-time gap: a later planning phase surfaces decisions or constraints not covered by an earlier one — return to the earlier phase and update it before proceeding. Do not paper over the gap by continuing forward.

A loop triggered and resolved is stronger than a plan that was never challenged.

**Loop diagnostic table — use when a gap surfaces during or after build:**

| Gap type | Root cause phase | What must be updated before building anything new |
|---|---|---|
| A screen or feature is missing at build end | Phase 2 — journey map incomplete | INVARIANTS.md: add UI completeness invariant; EXECUTION_PLAN.md: add missing tasks |
| CC makes a decision not covered in Claude.md | Phase 5 — Scope Boundary too loose | Claude.md: tighten scope or add invariant; re-verify affected tasks |
| Verification command fails due to wrong interface | Phase 3 — task CC prompt underspecified | EXECUTION_PLAN.md: rewrite CC prompt for affected task; produce new Claude.md version if invariant touched |
| A task invalidates a prior task's output | Phase 3 — session decomposition error | EXECUTION_PLAN.md: re-sequence affected tasks; re-verify from first affected task |
| An invariant cannot be enforced as written | Phase 2 — invariant is a goal not a constraint | INVARIANTS.md: reframe or remove; EXECUTION_PLAN.md: update the embedded invariant text in the affected task prompts |
| Open question resolved during build changes design | Phase 1 — Interrogate incomplete | ARCHITECTURE.md: document the decision; INVARIANTS.md: add any new constraints; produce new Claude.md version |

---

## Standard Repository Structure

All DataGrokr PBVI projects use a closed-contract folder structure. Every directory has a
defined purpose and a contract governing what may live inside it.

### Directory Inventory

| Directory / File | Purpose |
|---|---|
| `README.md` | Repo root — navigation and orientation for any engineer who clones |
| `PROJECT_MANIFEST.md` | Repo root — file registry for the entire project |
| `brief/` | Client inputs and requirements briefs — never modified after receipt |
| `docs/` | PBVI trunk artifacts (ARCHITECTURE.md, INVARIANTS.md, EXECUTION_PLAN.md, Claude.md) |
| `docs/prompts/` | CC execution prompts — methodology artifacts under version control |
| `sessions/` | Working evidence — SESSION_LOG.md and VERIFICATION_RECORD.md (engineer-facing) |
| `verification/` | Formal sign-off checklists — VERIFICATION_CHECKLIST.md per phase/enhancement (stakeholder-facing) |
| `discovery/` | BCE SIL artifacts + discovery/components/ for component files |
| `enhancements/` | REGISTRY.md + ENH-NNN subdirectory per enhancement |
| `tools/` | Agentic build automation scripts — challenge.sh, resume_challenge.sh, resume_session.sh, monitor.sh, launch.sh (optional automation wrapper). Methodology artifacts under version control. No source code, no planning artifacts. |

### The Three Structural Rules

All three rules are enforced in Claude.md and all CC prompts.

**Rule 1:** All file references use full paths from repo root — never bare filenames.

**Rule 2:** All files inside any enhancement package carry their ENH-NNN prefix — no exceptions.

**Rule 3:** Any file not in the mandatory set for its directory and not registered in
PROJECT_MANIFEST.md must not be read by CC as authoritative input. CC flags unregistered
files and reports them to the engineer before proceeding.

Rule 3 is the enforcement mechanism that makes PROJECT_MANIFEST.md meaningful rather than
advisory. Organic artifacts present in a repo that do not fit any directory contract are
untrusted until the engineer registers or removes them.

### Project Profiles

A closed-contract profile taxonomy determines which non-standard files are permitted in docs/
beyond the mandatory PBVI set. Profile declared in PROJECT_MANIFEST.md at project initialisation.

| Profile | Permitted additional files in docs/ |
|---|---|
| DATA_ACCELERATOR | POPULATION_MANIFEST.md, DATA_QUALITY_MANIFEST.md |
| WEB_APPLICATION | UI_SPEC.md, ROUTE_MAP.md |
| API_SERVICE | API_CONTRACT.md, RATE_LIMIT_POLICY.md |
| CLI_TOOL | COMMAND_SPEC.md |

Makes the directory standard extensible without making it open-ended.

### Directory Creation

All directories are created at project initialisation in a single scaffolding step — no
lifecycle-triggered creation. The semantic signal of "has this phase run" is carried by
PROJECT_MANIFEST.md status column (PRESENT/PENDING), not by directory existence.
Empty directories use .gitkeep files.

The tools/ directory is created at initialisation and pre-populated with the
five standard agentic build scripts from the DG-Forge repository. Scripts are
committed alongside the project and versioned with it. Never edit scripts
directly in a project — update the DG-Forge source and propagate.

---

## Project Initialisation

Everything in this section must exist before Phase 1 begins. A single CC initialisation
prompt scaffolds all directories, creates README.md and PROJECT_MANIFEST.md, and commits
the empty structure. This is the only correct way to start a PBVI project.

**Tool:** CC
**Trigger phrases:**
- "Initialise PBVI project"
- "Scaffold new PBVI project"
- "Set up PBVI project structure"

**Engineer provides before running:**
- `PROJECT_NAME` — the project name
- `PROFILE` — one of: DATA_ACCELERATOR | WEB_APPLICATION | API_SERVICE | CLI_TOOL
- `BRIEF_DESCRIPTION` — one paragraph, business purpose not technical description
- `INVARIANT_AUTHORSHIP_MODE` — ASSISTED (greenfield default) or GOVERNED (brownfield or explicit override). If not provided, default to ASSISTED and declare it in PROJECT_MANIFEST.md.
- `APPLICATION_SURFACE` (PBVI-011) — UI+API | UI_ONLY | API_ONLY | BACKGROUND_SERVICE.
  If known at initialisation (e.g. engineer has already run Phase 1 Interrogate), provide
  the value. If not yet known, leave blank — CC writes PENDING and the field is
  populated by CD declaration during Phase 1 Interrogate Application Profile output.

```
You are initialising a new PBVI project repository.

Engineer provides:
- PROJECT_NAME: [project name]
- PROFILE: [DATA_ACCELERATOR | WEB_APPLICATION | API_SERVICE | CLI_TOOL]
- BRIEF_DESCRIPTION: [one paragraph — business purpose, not technical description]
- INVARIANT_AUTHORSHIP_MODE: [ASSISTED | GOVERNED] — if not provided, default to ASSISTED
- APPLICATION_SURFACE: [UI+API | UI_ONLY | API_ONLY | BACKGROUND_SERVICE] — if not
  provided, write PENDING; CD declares this in Phase 1 Interrogate Application Profile
  output and the field is updated then.

If PROJECT_NAME, PROFILE, or BRIEF_DESCRIPTION are missing, stop and list what is needed. Do not proceed.

STEP 1 — Create mandatory directories with .gitkeep files:
  brief/.gitkeep
  docs/.gitkeep
  docs/prompts/.gitkeep
  sessions/.gitkeep
  verification/.gitkeep
  discovery/.gitkeep
  discovery/components/.gitkeep
  enhancements/.gitkeep
  tools/.gitkeep

Do not create any additional directories or files beyond what is specified in Steps 1b, 2 and 3.

STEP 1b — Copy automation scripts into tools/ from the DG-OS repository
(private repo: https://github.com/DataGrokrAnalytics/dg-os):

Run a non-interactive access check — try HTTPS first, then SSH.
Both checks must suppress credential prompts so they fail cleanly if access is not configured:
  GIT_TERMINAL_PROMPT=0 git ls-remote https://github.com/DataGrokrAnalytics/dg-os.git HEAD

If HTTPS check fails, try SSH:
  GIT_TERMINAL_PROMPT=0 git ls-remote git@github.com:DataGrokrAnalytics/dg-os.git HEAD

If either check succeeds, record the URL that worked as CLONE_URL. Then sparse-clone
just the tools/ directory and copy the five scripts:
  git clone --depth=1 --filter=blob:none --sparse [CLONE_URL] /tmp/dg-os-init
  git -C /tmp/dg-os-init sparse-checkout set tools
  cp /tmp/dg-os-init/tools/launch.sh tools/
  cp /tmp/dg-os-init/tools/resume_session.sh tools/
  cp /tmp/dg-os-init/tools/resume_challenge.sh tools/
  cp /tmp/dg-os-init/tools/challenge.sh tools/
  cp /tmp/dg-os-init/tools/monitor.sh tools/
  chmod +x tools/*.sh
  rm -rf /tmp/dg-os-init
  rm tools/.gitkeep
Proceed to STEP 2.

If both checks fail, output this block and continue to STEP 2:

  ⚠️  MANUAL STEP REQUIRED — tools/ scripts not copied.
  Git access to https://github.com/DataGrokrAnalytics/dg-os (private repo) could not be
  confirmed via HTTPS or SSH. You need read access configured via a GitHub token (HTTPS)
  or SSH key before scripts can be copied automatically.
  Copy these files from the DG-OS repository into this project's tools/ directory
  and run chmod +x tools/*.sh. Required for CC-direct operation: challenge.sh,
  resume_challenge.sh, resume_session.sh, monitor.sh. Optional automation wrapper:
  launch.sh (does not handle interactive CC permission prompts reliably).
    tools/challenge.sh
    tools/resume_challenge.sh
    tools/resume_session.sh
    tools/monitor.sh
    tools/launch.sh
  tools/.gitkeep has been left in place until scripts are added.

STEP 2 — Create README.md at repo root using PROJECT_NAME, PROFILE, and BRIEF_DESCRIPTION:

# [PROJECT_NAME]

## What This Is
[BRIEF_DESCRIPTION]

## Project Profile
Type: [PROFILE]
Status: Greenfield — Phase 1 not yet started.

## Where To Start
| If you want to... | Read this first |
|---|---|
| Understand the system | docs/ARCHITECTURE.md |
| Understand the constraints | docs/INVARIANTS.md |
| Understand the build history | sessions/ |
| Understand the current sign-off state | verification/ |
| Understand the system intelligence layer | discovery/INTAKE_SUMMARY.md |
| Work on an enhancement | enhancements/REGISTRY.md |

## Repository Structure
| Directory / File | Purpose |
|---|---|
| brief/ | Client inputs and requirements briefs — never modified after receipt |
| docs/ | PBVI trunk artifacts (ARCHITECTURE.md, INVARIANTS.md, EXECUTION_PLAN.md, Claude.md) |
| docs/prompts/ | CC execution prompts — methodology artifacts under version control |
| sessions/ | Working evidence — SESSION_LOG.md and VERIFICATION_RECORD.md |
| verification/ | Formal sign-off checklists — VERIFICATION_CHECKLIST.md per phase/enhancement |
| discovery/ | BCE SIL artifacts + discovery/components/ for component files |
| enhancements/ | REGISTRY.md + ENH-NNN subdirectory per enhancement |
| tools/ | Agentic build automation scripts — challenge.sh, resume_challenge.sh, resume_session.sh, monitor.sh, launch.sh (optional automation wrapper) |

## Rule Compliance
- Rule 1: All file references use full paths from repo root — never bare filenames.
- Rule 2: All files inside any enhancement package carry their ENH-NNN prefix — no exceptions.
- Rule 3: Any file not registered in PROJECT_MANIFEST.md must not be read by CC as authoritative input.

STEP 3 — Create PROJECT_MANIFEST.md at repo root with these mandatory sections in order.
All entries at initialisation carry Status: PENDING.

**METHODOLOGY_VERSION:** PBVI v[X.X] / BCE v[X.X]
Populate from the loaded skill frontmatter versions at initialisation.
Update this field only when the project is explicitly migrated to a new methodology version.

**INVARIANT_AUTHORSHIP_MODE:** [ASSISTED | GOVERNED]
Populate from engineer-provided value or default to ASSISTED.
ASSISTED = greenfield default (CD drafts structural and data invariants; engineer authors domain invariants).
GOVERNED = brownfield default or explicit override (engineer drafts first).
GOVERNED on greenfield requires a rationale comment: GOVERNED — [reason].

**INVARIANT_AUTHORSHIP_MODE:** [ASSISTED | GOVERNED]
Default: ASSISTED for greenfield builds (CD drafts structural and data invariants;
engineer authors domain invariants; all invariants engineer-signed-off).
Default: GOVERNED for brownfield and enhancement work (engineer drafts first).
GOVERNED on a greenfield project requires a written rationale on this line.
Declare at initialisation; do not change after Phase 2 begins.

**ONBOARDING_SOURCE:** [PBVI-009 brownfield onboarding | GREENFIELD]

**ONBOARDING_DATE:** [date — when PBVI-009 Step 5 was signed; blank for greenfield]

**ONBOARDING_LOG:** [discovery/ONBOARDING_LOG.md — when ONBOARDING_SOURCE = PBVI-009; blank for greenfield]

**APPLICATION_SURFACE:** [UI+API | UI_ONLY | API_ONLY | BACKGROUND_SERVICE | PENDING] (PBVI-011)
Populate from engineer-provided value at initialisation, or write PENDING.
PENDING value is replaced once CD declares the Application Profile in Phase 1 Interrogate.
Determines whether Phase 1 Decide runs UI Discovery, Phase 2 Step 0 runs the UI consistency
check, Phase 4 runs Step 1c UI Surface Review, Phase 6 Session 1 includes Playwright
scaffolding, and Phase 8 assembles UI_HARNESS.sh.

## Core Documents
| File | Status | Phase | Owner | Description |
|---|---|---|---|---|
| brief/ | PENDING | Pre-Phase 1 | Engineer | Requirements briefs — never modified after receipt |
| docs/ARCHITECTURE.md | PENDING | Phase 1 | Engineer | Architecture decisions and design rationale |
| docs/INVARIANTS.md | PENDING | Phase 2 | Engineer | System invariants — engineer-authored and signed |
| docs/EXECUTION_PLAN.md | PENDING | Phase 3 | Engineer | Task execution plan — frozen after Phase 4 gate |
| docs/PHASE4_GATE_RECORD.md | PENDING | Phase 4 | Engineer | Design Gate record — evaluation criteria, requirements traceability, stress test findings, risk register with dispositions |
| docs/Claude.md | PENDING | Phase 5 | Engineer | AI execution contract — frozen at creation |

> **UI projects only — APPLICATION_SURFACE contains UI (PBVI-011):** Add the following
> three rows to Core Documents. Mark N/A and omit for API_ONLY / BACKGROUND_SERVICE.
>
> | docs/UI_SURFACE.md | PENDING | Phase 1 | CD | Functional UI surface specification — dual-registered under Discovery Artifacts |
> | docs/SEED_DATA.md | PENDING/N-A | Phase 1 | CD | Seed data definition — produced only when data baseline = Seeded |
> | verification/UI_HARNESS.sh | PENDING | Phase 8 | CC | Playwright UI regression harness — assembled at Phase 8 step 9 |

## Non-Standard Registered Files
| File | Status | Phase | Owner | Description |
|---|---|---|---|---|
| *(none at initialisation)* | | | | |

## Non-Standard Registered Directories
| Directory | Status | Phase | Owner | Description |
|---|---|---|---|---|
| *(none at initialisation)* | | | | |

> **UI projects only — APPLICATION_SURFACE contains UI (PBVI-011):** Add the following
> row to Non-Standard Registered Directories.
>
> | ui_tests/ | PENDING | Phase 6 | CC | Playwright test files — one file per screen. Created by Session 1 scaffolding. |

## Session Logs
| File | Status | Phase | Owner | Description |
|---|---|---|---|---|
| *(populated as sessions run)* | | | | |

## Verification Records
| File | Status | Phase | Owner | Description |
|---|---|---|---|---|
| *(populated as sessions run)* | | | | |

## Verification Checklists
| File | Status | Phase | Owner | Description |
|---|---|---|---|---|
| *(populated at Phase 8)* | | | | |

## Discovery Artifacts
| File | Status | Phase | Owner | Description |
|---|---|---|---|---|
| discovery/INTAKE_SUMMARY.md | PENDING | Phase 8 | Engineer | BCE prerequisite artifact — Stage 1 |
| discovery/TOPOLOGY.md | PENDING | Phase 8 | Engineer | System topology — living extraction artifact |
| discovery/MODULE_CONTRACTS.md | PENDING | Phase 8 | Engineer | Module contracts — living extraction artifact |
| discovery/INTEGRATION_CONTRACTS.md | PENDING | Phase 8 | Engineer | Integration contracts — living extraction artifact |
| discovery/INVARIANT_CATALOGUE.md | PENDING | Phase 8 | Engineer | Invariant catalogue — living extraction artifact |
| discovery/RISK_REGISTER.md | PENDING | Phase 8 | Engineer | Risk register — living extraction artifact |
| discovery/ANNOTATION_CHECKLIST.md | PENDING | Phase 8 | Engineer | BCE attestation artifact — Stage 3 |

> **UI projects only — APPLICATION_SURFACE contains UI (PBVI-011):** UI_SURFACE.md is
> dual-registered. The Phase 1 row in Core Documents is the canonical entry; add the
> following discovery cross-reference row so BCE Stage 2/3 can locate the artifact.
>
> | docs/UI_SURFACE.md | (see Core Documents) | Phase 1 | CD | Discovery cross-reference — BCE Stage 2 reconciles page/route modules against the screen inventory |

## Enhancement Registry
| File | Status | Phase | Owner | Description |
|---|---|---|---|---|
| enhancements/REGISTRY.md | PENDING | Post-Phase 8 | Sprint Lead | Enhancement registry |

## Structural Exceptions
| File | Location | Reason |
|---|---|---|
| README.md | repo root | Universal repo convention — navigation and orientation only |
| PROJECT_MANIFEST.md | repo root | This file — registry cannot register itself |

STEP 4 — Commit:
git add .
git commit -m "chore: PBVI project initialisation — [PROJECT_NAME] scaffold"

After commit, output:
1. Confirm all 9 directories created
2. Confirm README.md and PROJECT_MANIFEST.md created
3. State the commit hash
4. State the tools/ setup outcome — one of:
   - "Tools ready — 5 scripts copied from https://github.com/DataGrokrAnalytics/dg-os."
   - "⚠️ Manual step required — copy tools/ scripts from https://github.com/DataGrokrAnalytics/dg-os before running sessions."
5. State: "Scaffold complete. Load pbvi_core.md and your requirements brief in CD,
   then use 'Let's start Phase 1'."
```

### README.md — Mandatory Template

README.md lives at repo root by universal convention — not inside any directory contract.
The initialisation prompt above generates README.md from the template embedded in the prompt.
Status field is updated at phase milestones — not static.

### PROJECT_MANIFEST.md

Lives at repo root. Is the file registry for the entire project. Tracks every file with:
target path, status (PRESENT/PENDING), phase ownership, owner, description.

Mandatory sections: Core Documents, Non-Standard Registered Files, Non-Standard Registered
Directories, Session Logs, Verification Records, Verification Checklists, Discovery Artifacts,
Enhancement Registry, Structural Exceptions.

### Structural Exceptions

README.md and PROJECT_MANIFEST.md are exempt from Rule 3 and directory contracts.
PROJECT_MANIFEST.md must include a Structural Exceptions section:

```markdown
## Structural Exceptions
| File | Location | Reason exempt from directory contracts |
|---|---|---|
| README.md | repo root | Universal repo convention — navigation and orientation only |
| PROJECT_MANIFEST.md | repo root | This file — registry cannot register itself |
```

---

## Phase 1 — Architecture

Three sub-phases in order:

### Interrogate
Goal: extract scope, constraints, and non-negotiables from the requirements brief.

**Tool:** CD
**Trigger phrases:**
- "Help me interrogate the requirements brief"
- "Run Phase 1 interrogation"
- "Let's start Phase 1"

**Reusable prompt:**
```
You are a senior software architect. Read the requirements brief below and produce:

1. Problem statement — what is the core problem the customer is actually trying to solve?
   Do not restate the requirements. Identify the underlying need.
2. Constraints — what must the system never do? Cover both stated constraints and
   implied ones not explicitly written.
3. Definition of success — if this is built correctly, what does success look like
   for the customer in concrete terms?
4. Failure modes — identify 3-4 system-level failures (not code bugs) that the
   design must protect against.
5. Missing information — what is absent from the brief that matters for design decisions?
6. Invocation boundary conditions — For each external trigger this system accepts (API call,
   scheduled job, user action, CLI command, event), enumerate the valid invocation states
   beyond the happy path: re-invocation against already-processed state, invocation with no
   new work available, invocation during or after a partial prior execution. For each state:
   what is the defined behaviour and what is the observable outcome?
7. Pipeline failure behaviour — for every multi-step process or pipeline in this system
   (LLM call chains, sync operations, multi-stage writes), state the defined behaviour when
   any individual step fails. For each step: what is the recovery path, what state is the
   system left in, and what is the observable outcome to the caller? If the architecture
   cannot answer any of these, flag it as a missing information item — not a build-time decision.
8. Application Profile (PBVI-011) — classify the system on four dimensions:

   a. Surface type
      Read the brief and classify as one of:
      - UI+API: the system has both a user-facing interface and a programmatic API
      - UI_ONLY: the system is a user-facing interface with no external API surface
      - API_ONLY: the system is a programmatic API with no user-facing interface
      - BACKGROUND_SERVICE: the system runs without user interaction (pipeline,
        scheduler, worker)
      State the classification and the evidence from the brief that supports it.
      This replaces the prior "Application surface type" item and determines which
      Phase 2 Step 0 checks apply.

   b. Authentication
      - Is authentication required? Y / N / Placeholder acceptable
      - If Y or Placeholder: what is the authentication mechanism implied by the brief?
        (session cookie, JWT, OAuth, SSO, other — or UNSPECIFIED if not stated)
      - If Placeholder: note this as a parking lot item in ARCHITECTURE.md

   c. User roles
      - List every distinct user type mentioned or implied in the brief.
      - For each: one-line access boundary (what they can do / what they cannot do).
      - If no role distinction exists: state "Single user type — no role differentiation."
      - If roles are mentioned but boundaries are unspecified: surface as missing
        information items.

   d. Data baseline
      At system launch, where does the initial data come from?
      - Seeded: representative data is defined and loaded at deployment
      - Migrated: data is imported from an existing system
      - User-generated: the system starts empty; users create all data
      - N/A: the system does not have a persistent data store
      If the brief does not specify: surface as a missing information item.

   APPLICATION_SURFACE field value for PROJECT_MANIFEST.md:
   [UI+API | UI_ONLY | API_ONLY | BACKGROUND_SERVICE]

   Note: The Application Profile is produced by CD reading the brief. CC writes the
   APPLICATION_SURFACE field into PROJECT_MANIFEST.md during scaffolding using the
   value declared here. When APPLICATION_SURFACE contains UI (UI+API or UI_ONLY),
   Phase 1 Decide runs UI Discovery after ARCHITECTURE.md is signed off — see the
   UI Discovery section below.

Be exhaustive on constraints. Flag anything vague.

[PASTE REQUIREMENTS BRIEF]

[BCE SUBGRAPH CONTEXT — paste here if enhancing a brownfield system with BCE artifacts.
Run "Query BCE subgraph for M-NNN" in CC (bce_core.md Section 16) to produce this.
Omit entirely for greenfield builds or when BCE artifacts are not yet available.]
```

### Explore
Goal: generate candidate architectures and evaluate trade-offs.

**Tool:** CD
**Trigger phrases:**
- "Help me explore architecture options"
- "Generate candidate architectures"
- "Run Phase 1 exploration"

**Reusable prompt:**
```
You are a senior software architect. Based on the constraints identified below, propose
3 candidate architectures. For each, describe:
- What it is — component breakdown and key technology choices
- What it makes easy
- What it makes hard
- Which constraints it satisfies — and flag any it doesn't fully satisfy
- What you'd be giving up compared to the other options

Do not make a recommendation. Present options so the engineer can make the selection decision.

[PASTE INTERROGATE OUTPUT]
```

**Explore → Decide Gap Check (mandatory before proceeding)**
Before moving to Decide, review the Explore output against the Interrogate output and answer:

"Did this exploration surface any design decisions — about product flow, data model, operational
behaviour, or component interaction — that are not traceable to a stated constraint, an implied
constraint, or a missing information item in the Interrogate output?"

If yes: stop. Return to Interrogate. Add the surfaced decisions as either implied constraints or
missing information items. Update the Interrogate output before proceeding to Decide.
If no: proceed to Decide.

Why this matters: Architecture exploration is generative — it surfaces decisions the requirements
brief did not explicitly expose. If those decisions are not traced back to Interrogate, they enter
ARCHITECTURE.md without a documented basis.

### Decide
Goal: select one architecture and lock it into authoritative documents.

**Human accountability gate:** Engineer makes the selection decision. Claude documents it.

**Conversation Quality Review:** Fires at the close of this phase gate — see Conversation Quality Review section.

**Traceability gate:** Before producing ARCHITECTURE.md, every design decision must be traceable to one of:
- A stated constraint from Interrogate
- An implied constraint from Interrogate
- A missing information item identified in Interrogate (now resolved)

**Tool:** CD
**Trigger phrases:**
- "Help me produce ARCHITECTURE.md"
- "Document the architecture decision"
- "Run Phase 1 decide step"

**Reusable prompt (post-decision):**
```
Produce ARCHITECTURE.md for the architecture selected below.

Output format: Plain Markdown file (.md). Not a Word document, not a PDF.
All PBVI planning artifacts are Markdown files committed to the repository.

Structure:
1. Problem framing — what does the system solve, and what does it explicitly not solve
2. Key design decisions — document ALL decisions made during Explore, regardless of count.
   For each: what was decided, rationale, alternatives rejected and why.
3. Challenge my decisions — for each decision, give the strongest argument against it,
   then state whether you consider the challenge valid or rejected, and why
4. Key risks
5. Key assumptions
6. Open questions
7. Future enhancements (parking lot) — conscious deferrals with rationale
8. Data model — if any, with all first-class entities, what each represents
9. Open questions — anything not yet resolved that Phase 3 depends on

My decision: [SELECTED APPROACH]
My reasons: [WHY THIS APPROACH OVER THE OTHERS — required.]
Interrogate output: [PASTE]
Explore output: [PASTE]
```

### UI Discovery (PBVI-011)

Goal: produce the functional surface specification for every screen the system requires,
so build prompts in Phase 3 onward have an explicit contract rather than an inferred one.

**Runs after:** ARCHITECTURE.md is engineer-signed-off.
**Gated on:** APPLICATION_SURFACE contains UI (UI+API or UI_ONLY). Skip entirely for
API_ONLY and BACKGROUND_SERVICE.

**Gate check (mandatory before UI Discovery begins):**
```
Read PROJECT_MANIFEST.md and check APPLICATION_SURFACE.
If APPLICATION_SURFACE is UI+API or UI_ONLY: proceed with UI Discovery.
If APPLICATION_SURFACE is API_ONLY or BACKGROUND_SERVICE: skip UI Discovery entirely.
Output: "UI Discovery — skipped. APPLICATION_SURFACE = [value]."
```

**Authorship:** CD-drafted from ARCHITECTURE.md and the requirements brief. Engineer
scans for errors, answers targeted gap questions, signs off. This is a correctness
scan, not a deep challenge session — UI will drift post-demo regardless, and the
artifact is designed for fast amendment.

**Amendment discipline:** Lightweight amendment log at the top of UI_SURFACE.md
(date, screen/section, change, reason). No challenge session required for amendments.

**Tool:** CD
**Trigger phrases:**
- "Run UI Discovery"
- "Produce UI_SURFACE.md"
- "Run Phase 1 UI Discovery"

**Reusable prompt — three passes in sequence:**
```
You are producing UI_SURFACE.md for this project. Run three passes in order.
Do not move to the next pass until the engineer has confirmed the current pass output.

--- PASS 0 — GLOBAL ELEMENTS ---

From ARCHITECTURE.md and the requirements brief, draft the Global Elements section
of UI_SURFACE.md. Cover all eight subsections: Navigation, Authentication Shell,
Back Navigation, Breadcrumbs, Global Error Boundary, App-level Loading,
Toast/Notification System.

For each subsection:
- Infer from ARCHITECTURE.md and brief where possible.
- Where you cannot infer with confidence, mark the field: TBD — [one-line question].
- Do not invent. Mark gaps explicitly.

After producing the draft, list every TBD item as a numbered gap question.
Present the draft and gap questions together. Wait for engineer to answer gaps
and confirm or correct the draft before proceeding to Pass 1.

Application Profile (from Interrogate):
- Surface type: [from Interrogate output]
- Auth: [from Interrogate output]
- Roles: [from Interrogate output]
- Data baseline: [from Interrogate output]

ARCHITECTURE.md: [PASTE or load from project files]
Requirements brief: [PASTE or load from project files]

--- PASS 1 — SCREEN INVENTORY ---

[Run after Pass 0 is confirmed]

From ARCHITECTURE.md, the requirements brief, and the confirmed Global Elements:

1. Enumerate every screen the system requires. For each:
   - Name (descriptive — e.g. "Invoice List", "Invoice Detail", "Create Invoice Form")
   - Type: List | Detail | Form | Dashboard | Modal | Wizard
   - Route: infer from convention or mark TBD
   - Journey: which user journey does this screen serve?
   - Roles: which roles can access this screen? Default to All if not determinable.
   - Auth required: Y | N

2. Verify the inventory is complete by checking:
   - Every entity in the data model has at least a List screen and a Detail or Form screen
     unless the brief explicitly excludes it.
   - Every action mentioned in the brief has a corresponding screen surface.
   - Every role has a complete journey — can accomplish their primary goal end-to-end
     without console or API access.
   - The Global Navigation items (Pass 0) each map to a screen in the inventory.

Present the Screen Inventory table. List any TBD items and screens where you
are uncertain of type or route. Wait for engineer confirmation before Pass 2.

--- PASS 2 — PER-SCREEN FUNCTIONAL SPEC ---

[Run after Pass 1 inventory is confirmed]

For each screen in the confirmed inventory, produce the full screen specification
using the UI_SURFACE.md schema (pbvi_templates.md Template 12). Work through screens
in journey order.

For each screen:
- Infer all fields from ARCHITECTURE.md data model, the requirements brief,
  and the confirmed Application Profile.
- Apply type-specific sections (List Configuration / Form Fields / Panels /
  Modal Configuration) only where the screen type requires them.
- For every field, action, or state you cannot infer: mark TBD — [specific question].
- Never invent behaviour. Mark gaps.

After completing all screen specs, produce a consolidated gap list:
one numbered question per TBD item, grouped by screen.

Present all screen specs and the consolidated gap list.
Wait for engineer to answer gaps and confirm or correct before finalising.

--- MISSING INFORMATION LOOP ---

After Pass 2: if any gap questions remain unanswered after engineer review,
surface them as additional missing information items. Present them in this format:

  UNRESOLVED UI GAPS — return to Interrogate
  ------------------------------------------
  These questions could not be resolved from available context. Add them to the
  Missing Information section of the Interrogate output and resolve before
  UI_SURFACE.md is finalised.

  [N]. Screen: [screen name] — [specific question]

Do not produce the final UI_SURFACE.md until all gaps are resolved or explicitly
marked as deferred with engineer acknowledgement.
```

**SEED_DATA.md production (conditional — runs after UI_SURFACE.md is confirmed):**
```
[Run only if data baseline = Seeded]

From the confirmed UI_SURFACE.md and ARCHITECTURE.md data model, produce SEED_DATA.md
using the schema in pbvi_templates.md Template 13.

For each first-class entity in the data model:
1. Determine the minimum record count required to enable all UI states defined in
   UI_SURFACE.md — e.g. enough records to show pagination, enough status variants
   to show conditional action visibility.
2. Define representative seed records — realistic values, not placeholder strings.
3. Produce the Seed Coverage Matrix: map each screen state in UI_SURFACE.md to
   the seed records that enable it.

Mark any entity where you cannot determine representative values as TBD.
Present the draft. Wait for engineer confirmation before finalising.
```

**Sign-off gate:** Both UI_SURFACE.md and SEED_DATA.md (if applicable) must be
engineer-signed-off before Phase 1 closes. CC commits both artifacts to `docs/`
and registers them in PROJECT_MANIFEST.md (Planning Artifacts and Discovery
Artifacts sections — `UI_SURFACE.md` is dual-registered).

---

## Phase 2 — Invariant Definition

**Purpose:** Define conditions that must never break before planning how to build.
Invariants are not goals — they are constraints. If any invariant is violated,
the system is broken regardless of what else works.

**Gate condition:** INVARIANTS.md must be complete and engineer-signed-off before
Phase 3 begins. Every invariant in the final set must pass all five challenge tests —
including the harm and detectability test — before the engineer signs off. Claude may
not proceed to execution planning without this.

**Conversation Quality Review:** Fires at the close of this phase gate — see Conversation Quality Review section.

**Authorship rule:** Three categories; authorship splits by category.

| Category | What it covers | Authorship |
|---|---|---|
| Structural | Derived from architecture — data flow, component boundaries, state mutation rules | CD drafts. Engineer confirms. |
| Data | Derived from schema — cardinality, nullability, state machine constraints | CD drafts. Engineer confirms. |
| Domain | Business rules, operational constraints — anything not visible in architecture or data model | Engineer authors. CD challenges for completeness. |

**INVARIANT_AUTHORSHIP_MODE** — declared in PROJECT_MANIFEST.md at initialisation.
- Greenfield default: `ASSISTED` (three-category model above)
- Brownfield default: `GOVERNED` (engineer drafts first — operational history CD cannot see)
- GOVERNED on greenfield requires written rationale in PROJECT_MANIFEST.md

In ASSISTED mode the sign-off question shifts from "did you write these?" to "do you stand behind these?" Domain invariant authorship cannot be delegated in either mode.

**Revision rule:** Claude may suggest exact reframings and may draft revisions for
engineer approval. The engineer must approve every revision. If the engineer is
satisfied with a draft revision without changes, that approval is the sign-off.

**Failure Mode Draft:** CD produces a three-part failure mode entry alongside every
structural and data invariant it drafts:
1. **Violation observable state** — the specific condition that exists when the invariant is broken
2. **Detection point** — where and when the violation becomes visible (DB constraint at write time / application layer / verification test / production report / user report)
3. **Blast radius** — consequence downstream (data corruption, incorrect business decision, silent wrong answer, security exposure, financial loss)

Domain invariant failure modes are engineer-authored, consistent with the authorship split.
CD challenges domain failure modes for completeness and blind spots.
Failure Mode Draft entries are embedded in INVARIANTS.md alongside each invariant —
they are the specification for Phase 8 harness assertions, not documentation.

**Reclassification rule:** An invariant that fails the harm and detectability test
is not discarded. It is reclassified as implementation guidance and embedded in the
CC prompt of the relevant task(s) in EXECUTION_PLAN.md, with a one-line note
explaining why it was reclassified. It does not go into INVARIANTS.md and it does
not go into Claude.md.

**Version compatibility check — mandatory before this phase begins:**
Read PROJECT_MANIFEST.md and locate the METHODOLOGY_VERSION field.
Compare it against the version in this skill's frontmatter.
If they match: proceed silently.
If they differ or the field is absent: output the following, then continue —
do not stop.

  METHODOLOGY VERSION WARNING
  ---------------------------
  Skill version:    [from skill frontmatter]
  Project version:  [from METHODOLOGY_VERSION field, or NOT DECLARED]

  This project was initialised under a different methodology version.
  Proceeding may produce incomplete or unexpected results.
  Consult BREAKING_CHANGES.md in the DG-Forge repo to identify which migrations apply.
  Then use the migration trigger phrases in the Version Migration section of this skill.

**Three steps in order:**

**Step 0 — Map data touch points before drafting:**

Before writing a single invariant, enumerate every place data enters, transforms,
or exits the system. Common touch points: Capture, Storage (write/read/update),
Retrieval, Transformation, Transmission, Rendering, Authentication.

**Step 0 — APPLICATION_SURFACE-conditional behaviour (PBVI-011):**

Read PROJECT_MANIFEST.md and check APPLICATION_SURFACE.

*For UI+API and UI_ONLY projects:* UI_SURFACE.md already exists from Phase 1 Decide.
Do NOT re-produce a separate journey map. Instead, run the consistency check:

1. Load UI_SURFACE.md and the data touch point inventory above.
2. For each data touch point (Capture, Storage, Retrieval, Transformation,
   Transmission, Rendering, Authentication): confirm it maps to at least one
   screen or global element in UI_SURFACE.md.
3. For each screen in UI_SURFACE.md: confirm its Data Displayed section maps
   to at least one data touch point in the inventory.
4. Surface any gaps — touch points with no screen coverage, or screens with
   no corresponding touch point.

If gaps exist: return to Phase 1 UI Discovery and resolve before proceeding to
invariant drafting. If no gaps: proceed to Step 1.

*For API_ONLY and BACKGROUND_SERVICE projects:* Step 0 is unchanged — produce
the data touch point inventory as before. A journey map is produced only if there
is a non-trivial user-facing surface (e.g. an admin console or monitoring
dashboard); otherwise omit.

**Tool:** CD
**Trigger phrases (ASSISTED — greenfield default):**
- "Draft invariants for this system"
- "Help me define invariants"
- "Run Phase 2 invariant challenge"

**Trigger phrases (GOVERNED — brownfield / explicit override):**
- "Challenge my invariants"
- "Review my invariant draft"

**Step 1 — ASSISTED mode (greenfield default): CD drafts structural and data invariants**
\```
Draft the candidate structural and data invariants for this system from
ARCHITECTURE.md and the data model below.

Structural invariants — derived from architecture decisions (data flow,
component boundaries, state mutation rules).

Data invariants — derived from schema and entity relationships (cardinality,
nullability, state machine constraints).

For each invariant you draft, also produce the Failure Mode Draft:
1. Violation observable state — the specific condition that exists when broken
2. Detection point — where and when the violation becomes visible
   (DB constraint at write time / application layer / verification test /
   production report / user report)
3. Blast radius — downstream consequence (data corruption, incorrect business
   decision, silent wrong answer, security exposure, financial loss)

Apply all five challenge tests plus the complexity accumulation test to every
invariant you draft — goal vs. constraint, enforcement scope, bundling, coverage
(map to data touch point inventory from Step 0), harm and detectability,
complexity accumulation. Surface only invariants that pass all six tests.

If APPLICATION_SURFACE contains UI (PBVI-011), also check against UI_SURFACE.md:
(a) Every API endpoint that modifies state has a corresponding Action entry in
    UI_SURFACE.md on at least one screen.
(b) Every role in the Application Profile can complete their primary journey
    end-to-end using only screens defined in UI_SURFACE.md — no console or
    API access required.
(c) Every screen in UI_SURFACE.md maps to at least one user goal in the
    requirements brief.
(d) Every conditional action in UI_SURFACE.md (Condition column ≠ Always) has
    a corresponding data invariant or domain invariant that governs the condition.
    If none exists: surface as a missing invariant candidate.

After producing structural and data invariants, prompt the engineer:
"These are the structural and data invariants I can infer from the architecture
and data model. Now: what business rules exist for this system that are not
visible in the architecture or data model? Those are domain invariants — I
cannot draft them. State each one and I will challenge it against all six tests."

ARCHITECTURE.md: [PASTE]
Data model: [PASTE or state if not yet documented]
Data touch point inventory from Step 0: [PASTE]
\```

**Step 1 — GOVERNED mode (brownfield / explicit override): Engineer proposes, Claude challenges**
\```
I have drafted the following invariants for this system. Challenge this set:
- Are any conditions missing across data correctness, security boundaries,
  and operational guarantees?
- If APPLICATION_SURFACE contains UI (PBVI-011): is there an invariant for each
  of the following — checked against UI_SURFACE.md?
  (a) Every API endpoint that modifies state has a corresponding Action entry
      in UI_SURFACE.md on at least one screen.
  (b) Every role in the Application Profile can complete their primary journey
      end-to-end using only screens defined in UI_SURFACE.md — no console or
      API access required.
  (c) Every screen in UI_SURFACE.md maps to at least one user goal in the
      requirements brief.
  (d) Every conditional action in UI_SURFACE.md (Condition column ≠ Always) has
      a corresponding data or domain invariant governing the condition. Flag
      any conditional action without one as a missing invariant candidate.
- Are any stated as goals rather than constraints?
- For each: could an implementation pass all current test cases while still
  violating this invariant? If yes, flag it.
- Are any invariants bundling two separate enforcement points? If so, flag for splitting.

My proposed invariants:
[ENGINEER'S DRAFT]
\```

**Challenge checklist — Claude applies all five to every invariant:**

Goal vs. constraint test: Can a test be written that would fail if this condition is
violated? If no test is conceivable, it is likely a goal. Flag it.

Enforcement scope test: Are all enforcement points listed? Flag any invariant where a
secondary write or read path is unaddressed.

Bundling test: Does a single invariant span two unrelated enforcement layers? Flag and
suggest the split.

Coverage test: Map each invariant back to the data touch point map from Step 0. Flag
any touch point boundary with no corresponding invariant.

Harm and detectability test: If Claude Code violates this invariant silently during
build, does the violation cause harm that cannot be easily detected and corrected after
the fact? To remain in INVARIANTS.md, both conditions must hold: the harm is real and
significant, AND the violation is not immediately visible through normal use, inspection,
or output review. If either condition fails, reclassify it as implementation guidance
embedded in the relevant task prompts in EXECUTION_PLAN.md.

Complexity accumulation test: does this architecture force conditional logic to accumulate
in a single component or handler? If a component's design implies it must handle multiple
variants, states, or paths, flag it — the architecture may be creating unavoidable
complexity before a line of code is written.

**Classification challenge — Claude applies to every invariant that passes all five tests:**

Does this invariant apply to every task in the system regardless of what is being built,
or only to tasks that touch a specific component, feature, or data boundary? If any task
in the plan could plausibly execute without this invariant being relevant, it is
TASK-SCOPED. If it must be held across every task without exception, it is GLOBAL.
Claude proposes the classification; the engineer confirms or overrides at sign-off.

**Step 1b — Sufficiency check against ARCHITECTURE.md:**

After Step 1 revision, Claude reads ARCHITECTURE.md section by section and checks the
invariant set for sufficiency. For each section: does this section imply a system
constraint that has no corresponding invariant?

Sections to check: Data model, Design decisions, Key risks, Key assumptions, Open
questions, Out of scope decisions, any other section present.

Claude surfaces gaps only — it does not generate invariant text. In ASSISTED mode,
gaps go to the engineer with the same instruction: state each as a domain invariant
if you own it, and Claude will challenge it.

Reusable prompt for Step 1b:
```
Read ARCHITECTURE.md below and check the current invariant set for sufficiency.
Work through ARCHITECTURE.md section by section. For each section, identify any
gaps: places where the architecture implies a system constraint that has no
corresponding invariant. For each gap: name the section it came from, state what
is uncovered, and explain why it matters as a system constraint. Do not write
invariant text. Flag only.
ARCHITECTURE.md: [PASTE]
Current invariant set: [PASTE]
```

**Step 2 — Produce INVARIANTS.md:**
\```
Produce INVARIANTS.md from the agreed invariant set below.

For each invariant:
- INV-XX: [condition that must always be true]
- Category: Structural | Data | Domain
- Scope: GLOBAL | TASK-SCOPED
- Authorship: CD-drafted (confirmed by engineer) | Engineer-authored
- Why this matters: concrete failure scenario if violated
- Enforcement points: specific locations in the system where this must be enforced
- Failure Mode:
    Violation: [observable state when the invariant is broken]
    Detection: [where and when it becomes visible — DB constraint / application layer /
    verification test / production report / user report]
    Blast radius: [downstream consequence]

GLOBAL: applies to every task in the system — goes into Claude.md Section 2.
TASK-SCOPED: applies only when specific components or features are touched — embedded
inline in the CC prompt of each relevant task in EXECUTION_PLAN.md.

Agreed set: [PASTE FINAL LIST]
For CD-drafted invariants: Failure Mode Drafts are already produced from Step 1 — embed them.
For engineer-authored domain invariants: engineer provides the three-part failure mode.
\```

---

## Phase 3 — Execution Planning

**Gate condition:** ARCHITECTURE.md and INVARIANTS.md must be complete and
engineer-signed-off. All open questions in ARCHITECTURE.md must be resolved
with concrete decisions before this prompt runs. For enhancements: the Phase 3
Gate — Tier Reconfirmation in ENH-NNN_SCOPE.md must be completed and signed
off before this prompt runs.

**UI Discovery gate (PBVI-011):** If APPLICATION_SURFACE contains UI (UI+API or
UI_ONLY), UI_SURFACE.md must be present and engineer-signed-off before Phase 3
runs. If absent: stop and return to Phase 1 UI Discovery — Phase 3 cannot generate
UI test specs (item 7) without it.

**Conversation Quality Review:** Fires at the close of this phase gate — see Conversation Quality Review section.

**Tier reconfirmation (enhancements only):** Before running the Phase 3
prompt, ask the engineer in CD:

"Before we proceed to execution planning: is the Sign-Off Tier declared in
SCOPE.md Section 6 still appropriate given what Phases 1 and 2 surfaced?
If anything in Interrogate or the invariant challenge changed the scope, type,
or invariant footprint of this enhancement beyond what was visible at scoping
time, update SCOPE.md Section 6 and the Tier Reconfirmation section now.
If the Tier is unchanged, check the reconfirmation box and we can proceed."

Wait for engineer confirmation before running the execution planning prompt.
This is a human gate — Claude does not assess whether the Tier is appropriate.

**Version compatibility check — mandatory before this phase begins:**
Read PROJECT_MANIFEST.md and locate the METHODOLOGY_VERSION field.
Compare it against the version in this skill's frontmatter.
If they match: proceed silently.
If they differ or the field is absent: output the following, then continue —
do not stop.

  METHODOLOGY VERSION WARNING
  ---------------------------
  Skill version:    [from skill frontmatter]
  Project version:  [from METHODOLOGY_VERSION field, or NOT DECLARED]

  This project was initialised under a different methodology version.
  Proceeding may produce incomplete or unexpected results.
  Consult BREAKING_CHANGES.md in the DG-Forge repo to identify which migrations apply.
  Then use the migration trigger phrases in the Version Migration section of this skill.

**Requirements traceability check** (mandatory before generating the plan):

Cross-reference the requirements brief against ARCHITECTURE.md. For every named
feature, behaviour, or deliverable in the brief, confirm it has either:
(a) a corresponding design decision in ARCHITECTURE.md, or (b) an explicit deferral.

**Tool:** CD
**Trigger phrases:**
- "Help me produce the execution plan"
- "Generate EXECUTION_PLAN.md"
- "Run Phase 3"

**Reusable prompt:**
\```
I have the architecture and invariants defined (see below). Before producing
the execution plan, confirm that all open questions from ARCHITECTURE.md are
resolved. If any remain unresolved, list them and stop.

Produce execution_plan.md structured as follows:
- Resolved decisions table: open questions closed with concrete answers
- Session overview table: session name, goal, task count, estimated duration
- Per session:
  - Session goal: what running, verifiable state does this session deliver?
  - Integration check: exact shell command to verify the session as a whole
  - Tasks: each task must produce a discrete, independently verifiable output

For each task:
1. Description — what it builds, inputs and outputs
2. CC prompt — exact prompt to give Claude Code
3. Test cases — scenarios with expected outcomes (happy path and failure cases)
4. Verification command — exact shell command, not "run the tests"
5. Invariant enforcement — list each TASK-SCOPED invariant that applies to this task
   with its full condition text embedded inline in the CC prompt. GLOBAL invariants
   (in Claude.md Section 2) apply to all tasks and need not be repeated per task.
6. Regression classification — one of three values, with a one-line rationale:
   - NOT-REGRESSION-RELEVANT: verification command is session-specific or non-portable.
   - REGRESSION-RELEVANT: portable verification command, runnable from repo root without
     session-specific setup. Included in REGRESSION_SUITE.sh at Phase 8.
   - HARNESS-CANDIDATE: stricter subset of REGRESSION-RELEVANT. The assertion is stateless,
     portable, executable against a running system without build context, and directly tied
     to a named invariant in INVARIANTS.md. Included in both REGRESSION_SUITE.sh and
     HARNESS.sh at Phase 8.
   AI classifies at generation time; engineer confirms at sign-off.
7. UI test spec (PBVI-011) — applies only to tasks that build or modify a screen
   defined in UI_SURFACE.md. For all other tasks, omit this field.

   Reference the relevant screen entry in UI_SURFACE.md. For the screen(s) this
   task builds, specify the Playwright test assertions CC must write as part of
   completing this task:

     Screen: [screen name from UI_SURFACE.md]
     Test strategy: [Seeded — tests run against seed state | User-generated —
                     tests drive UI to create required state | N/A]

     Assertions to implement:
     - [assertion description — what Playwright should verify, referencing States,
       Actions, and conditional behaviour from UI_SURFACE.md]

     Test file path: ui_tests/[screen-slug].spec.ts

   AI generates assertions at plan time from UI_SURFACE.md; engineer confirms at
   sign-off. These assertions are not optional — they are part of the task
   completion criteria and must be committed in the same commit as the
   implementation.

Session 1 must include a scaffolding task as its first task.

**Session 1 scaffolding for UI projects (PBVI-011, APPLICATION_SURFACE contains UI):**
The Session 1 scaffolding task must include the following in its CC prompt:
- Install Playwright as a dev dependency.
- Initialise Playwright config: write `playwright.config.ts` at repo root.
- Create the `ui_tests/` directory.
- Register `ui_tests/` in PROJECT_MANIFEST.md under Non-Standard Registered
  Directories (Status: PRESENT after this task; Phase: Phase 6; Owner: CC).
Verification: confirm Playwright is installed and `npx playwright --version` runs;
confirm `playwright.config.ts` and `ui_tests/` exist.

**Session 1 seed script task (conditional — data baseline = Seeded only, PBVI-011):**
Include a seed script task as the SECOND task in Session 1 (after scaffolding):
- Description: implement the seed script from SEED_DATA.md.
- CC prompt: produce scripts/seed.[ts|sql|js] implementing all entities and
  records defined in SEED_DATA.md. Script must be idempotent.
- Verification: run the seed script; confirm record counts per entity match
  SEED_DATA.md minimum counts.
- Regression classification: REGRESSION-RELEVANT.

The seed script task is not optional and is not deferred when data baseline =
Seeded. Development, UI testing, and demo readiness all depend on seed data
existing.

ARCHITECTURE.md: [PASTE]
INVARIANTS.md: [PASTE]
UI_SURFACE.md: [PASTE — required if APPLICATION_SURFACE contains UI; omit otherwise]
SEED_DATA.md: [PASTE — required if data baseline = Seeded; omit otherwise]
Resolved decisions: [LIST ALL OPEN QUESTIONS WITH CONCRETE ANSWERS]
\```

---

## Phase 4 — Design Gate

**Purpose:** Before any code is written, confirm the plan is complete and
coherent, and that the engineer owns it. Two steps. Both must complete before Phase 5 begins.

**Claude.md does not exist until this gate passes.**

**Version compatibility check — mandatory before this phase begins:**
Read PROJECT_MANIFEST.md and locate the METHODOLOGY_VERSION field.
Compare it against the version in this skill's frontmatter.
If they match: proceed silently.
If they differ or the field is absent: output the following, then continue —
do not stop.

  METHODOLOGY VERSION WARNING
  ---------------------------
  Skill version:    [from skill frontmatter]
  Project version:  [from METHODOLOGY_VERSION field, or NOT DECLARED]

  This project was initialised under a different methodology version.
  Proceeding may produce incomplete or unexpected results.
  Consult BREAKING_CHANGES.md in the DG-Forge repo to identify which migrations apply.
  Then use the migration trigger phrases in the Version Migration section of this skill.

### Step 1 — Structured Plan Review (AI-assisted)

Requires all four documents: Requirements Brief, ARCHITECTURE.md, INVARIANTS.md,
EXECUTION_PLAN.md. If any are missing, stop.

**Tool:** CD
**Trigger phrases:**
- "Run the design gate"
- "Review the execution plan"
- "Run Phase 4"

**Review prompt:**
```
You are conducting a rigorous technical architecture review for a PBVI project.

Before starting: confirm all four documents are present — Requirements Brief,
ARCHITECTURE.md, INVARIANTS.md, EXECUTION_PLAN.md. If any are missing, stop.

Complete this review in four steps:

## STEP A — EVALUATION CRITERIA
Derive 8-10 criteria from INVARIANTS.md. Supplement with universal criteria only
where invariants do not cover a dimension.

## STEP B — REQUIREMENTS TRACEABILITY
For EACH requirement: which architecture component addresses it? Which task implements
it? Rate: FULLY MET / PARTIALLY MET / NOT ADDRESSED / CONTRADICTED.
Also check: every invariant has at least one task touching it with sufficient
verification.

## STEP C — ADVERSARIAL STRESS TEST
Attack: DATA, INFRASTRUCTURE, EXECUTION, SECURITY, ARCHITECTURE vs PLAN GAP.

## STEP D — PRIORITIZED FINDINGS
Risk register table:
| # | Finding | Severity | Requirement or Invariant Affected | Return to Phase | Recommendation |

Overall verdict: APPROVE / CONDITIONAL APPROVE / REVISE AND RESUBMIT
Top 3 blockers. Confidence level (0–100%).
```

After the risk register: assign RESOLVE or ACCEPT to each finding. For each ACCEPT,
provide a rationale. Save the complete gate record — all four steps plus dispositions —
as `docs/PHASE4_GATE_RECORD.md` using the template from pbvi_templates.md.

### Step 1c — UI Surface Review (PBVI-011)

**Runs as part of Step 1. Gated on APPLICATION_SURFACE containing UI (UI+API or UI_ONLY).
For API_ONLY and BACKGROUND_SERVICE, mark N/A and skip.**

**Tool:** CD
**Trigger phrase:** "Run UI Design Gate"

**Review prompt:**
```
You are running the Phase 4 UI Surface Review (Step 1c).

Load UI_SURFACE.md and EXECUTION_PLAN.md. Complete four checks:

CHECK 1 — Screen coverage
For every screen in UI_SURFACE.md Screen Inventory: confirm at least one task
in EXECUTION_PLAN.md is responsible for building it. Flag any screen with no
corresponding task.

CHECK 2 — Role-conditional behaviour testability
For every conditional action in UI_SURFACE.md (Condition column ≠ Always):
confirm the condition is testable — either via a named invariant in INVARIANTS.md
or via a UI test spec (EXECUTION_PLAN.md item 7) on the relevant task. Flag any
condition with no testability path.

CHECK 3 — Global elements coverage
Confirm the following global elements have at least one EXECUTION_PLAN.md task
responsible for them: Navigation, Logout, Session expiry handling, Global error
boundary. Flag any that are absent from the plan.

CHECK 4 — Auth architecture consistency
Confirm the auth mechanism declared in UI_SURFACE.md Authentication Shell is
consistent with the auth approach documented in ARCHITECTURE.md. Flag any
inconsistency.

Output: table of findings per check, severity (BLOCKER | WARNING | INFO),
and recommendation. Blockers must be resolved before Phase 5 opens.
Add findings to PHASE4_GATE_RECORD.md Section F (UI Surface Review).
```

**Step 1c gate:** Verdict must be PASS or CONDITIONAL. BLOCKED verdict requires
returning to UI Discovery or amending EXECUTION_PLAN.md before Step 2 opens.

**Step 1 gate:** All RESOLVE findings addressed. Verdict must be APPROVE or CONDITIONAL
APPROVE before Step 2 begins. Step 1c gate must also pass (or be marked N/A for
non-UI projects).

**Conversation Quality Review:** Fires after Step 2 sign-off (including Step 2b — Invariant Failure Mode Review) — see Conversation Quality Review section.

### Step 2 — Engineer Ownership Confirmation (Human Only)

No documents open. Three questions answered from memory:
1. Can I explain what this system does and why it is designed this way?
2. Do I agree with every key architectural decision?
3. Do I know what failure looks like for each invariant — specifically?

Claude may not declare this gate passed — only the engineer signs off.

### Step 2b — Invariant Failure Mode Review

For each invariant in INVARIANTS.md, work through the failure mode in sequence:

**Structural and data invariants (CD-drafted failure modes):**
CD reads the Failure Mode entry aloud. Engineer confirms, corrects, or augments each
of the three parts — violation observable state, detection point, blast radius.
Correction or augmentation is evidence of ownership.
Inability to engage with the failure mode at all is a gate failure — the invariant
returns to Phase 2 before Phase 5 opens.

**Domain invariants (engineer-authored failure modes):**
Engineer states the three-part failure mode without reference to any document.
CD challenges for completeness and blind spots.

**Ownership test:**
An engineer who can confirm, correct, or augment a failure mode statement owns the invariant.
An engineer who cannot engage with it does not.

**Gate failure consequence:** Any invariant that fails the ownership test returns to
Phase 2. Phase 5 does not open until every invariant passes.

The failure mode entry for each invariant is the specification for the Phase 8 harness
assertion that guards it. A complete three-part failure mode directly implies what
the harness must test.

---

## Phase 5 — Claude.md Creation

**Purpose:** Produce the frozen execution contract Claude Code works against
in Phase 6. Phase 4 gate must pass before this phase begins.

**Version compatibility check — mandatory before this phase begins:**
Read PROJECT_MANIFEST.md and locate the METHODOLOGY_VERSION field.
Compare it against the version in this skill's frontmatter.
If they match: proceed silently.
If they differ or the field is absent: output the following, then continue —
do not stop.

  METHODOLOGY VERSION WARNING
  ---------------------------
  Skill version:    [from skill frontmatter]
  Project version:  [from METHODOLOGY_VERSION field, or NOT DECLARED]

  This project was initialised under a different methodology version.
  Proceeding may produce incomplete or unexpected results.
  Consult BREAKING_CHANGES.md in the DG-Forge repo to identify which migrations apply.
  Then use the migration trigger phrases in the Version Migration section of this skill.

**Five required sections:**
1. **System Intent** — what it does, what it doesn't, what success looks like (2-3 sentences)
2. **Hard Invariants** — GLOBAL invariants only: conditions that are genuinely cross-cutting
   and apply to every task regardless of feature area. Maximum five engineer-defined invariants.
   TASK-SCOPED invariants are embedded in task prompts in EXECUTION_PLAN.md and do not appear here.
   One methodology-mandated invariant is pre-declared in every Claude.md — it does not consume
   an engineer slot and cannot be removed:
   `INVARIANT: Each function, method, or handler must have a single stateable purpose.
   Conditional nesting exceeding two levels is a structural violation — refactor before
   proceeding. This is never negotiable.`
   Format for engineer invariants: `INVARIANT: [condition]. This is never negotiable.`
3. **Scope Boundary** — exact files CC is permitted to create or modify.
   If a task conflicts with an invariant: invariant wins — flag, never resolve silently.
4. **Fixed Stack** — exact technologies, versions, dependencies, environment variable names.
   If not listed, CC will choose its own.
5. **Rules** — all three structural rules verbatim:
   - Rule 1: All file references use full paths from repo root — never bare filenames.
   - Rule 2: All files inside any enhancement package carry their ENH-NNN prefix — no exceptions.
   - Rule 3: Any file not in the mandatory set for its directory and not registered in PROJECT_MANIFEST.md must not be read by CC as authoritative input. CC flags unregistered files and reports them to the engineer before proceeding.

**Immutability doctrine:** Claude.md is frozen at creation.
Version header: `# Claude.md — v1.0 · FROZEN · [date]`

If Phase 6 reveals Claude.md needs to change: stop build, return to Claude Desktop,
update the relevant planning artifact, produce a new versioned Claude.md, resume and
re-verify all affected tasks. **Never edit Claude.md inline during Phase 6. Never.**

**Tool:** CD
**Trigger phrases:**
- "Produce Claude.md"
- "Generate Claude.md"
- "Run Phase 5"

**Reusable prompt:**
\```
Produce Claude.md for this system using exactly these five sections:

1. System Intent — 2-3 sentences only. What it does, what it explicitly does
   not do, what success looks like.

2. Hard Invariants — GLOBAL invariants only, sourced from INVARIANTS.md Scope: GLOBAL
   entries. Do not include TASK-SCOPED invariants — they are embedded in task prompts
   in EXECUTION_PLAN.md. Maximum five engineer-defined invariants.
   Pre-declare the following methodology-mandated invariant first — it does not consume
   an engineer slot and cannot be removed:
   INVARIANT: Each function, method, or handler must have a single stateable purpose.
   Conditional nesting exceeding two levels is a structural violation — refactor before
   proceeding. This is never negotiable.
   Format for engineer invariants: INVARIANT: [condition]. This is never negotiable.

3. Scope Boundary — list exact files CC may create or modify. State what CC
   must not do. State: if a task prompt conflicts with an invariant, the
   invariant wins — flag it, never resolve silently.

4. Fixed Stack — exact technologies, versions, dependency names, environment
   variable names. If not listed here, CC will choose its own.

5. Rules — include all three structural rules verbatim:
   Rule 1: All file references use full paths from repo root — never bare filenames.
   Rule 2: All files inside any enhancement package carry their ENH-NNN prefix — no exceptions.
   Rule 3: Any file not in the mandatory set for its directory and not registered in
   PROJECT_MANIFEST.md must not be read by CC as authoritative input. CC flags
   unregistered files and reports them to the engineer before proceeding.

6. UI Surface (PBVI-011 — include only if APPLICATION_SURFACE contains UI) —
   session-scoped UI context for CC. Add a section in this format:

   ## UI Surface
   Data baseline: [Seeded | Migrated | User-generated]
   Test strategy: [Seeded: run against seed state | Other: drive via UI]
   Playwright test directory: ui_tests/

   Global elements in effect:
   [Paste Navigation type, Auth shell logout location, Back navigation mechanism,
    Global error boundary behaviour from UI_SURFACE.md Global Elements section.
    Global Elements are always included in full — they are cross-cutting.]

   Screens in scope for this session:
   [Paste only the screen entries from UI_SURFACE.md that correspond to tasks
    in this session's EXECUTION_PLAN.md. Do NOT include the full UI_SURFACE.md —
    include only screens CC will build in this session. For each session-scoped
    screen, include the full screen specification: Data Displayed, Actions,
    States, type-specific sections (List/Form/Dashboard/Modal), Async Behaviour.]

   Note: Claude.md is session-scoped — Phase 5 produces one Claude.md per session
   for UI projects. Sessions covering different screens get different Claude.md
   instances.

Version header (first line): # Claude.md — v1.0 · FROZEN · [date]
Use ARCHITECTURE.md, INVARIANTS.md, and EXECUTION_PLAN.md from Project files if
available. If not in Project files, they must be pasted below before running this
prompt — do not produce Claude.md without all three documents present.

UI Surface production gate (PBVI-011): If APPLICATION_SURFACE contains UI and
UI_SURFACE.md is absent from project files, stop. UI_SURFACE.md must be present
before Claude.md can be produced for a UI project.

Aim for under 80 lines for non-UI projects. UI projects will be longer due to the
session-scoped UI Surface section (proportional to the number of screens in scope
for the session).

[If not in Project files, paste here:]
ARCHITECTURE.md: 
INVARIANTS.md: 
EXECUTION_PLAN.md:
UI_SURFACE.md:  [Required if APPLICATION_SURFACE contains UI. Omit otherwise.]
\```

### Session Prompt Files — Greenfield Path Convention

Session prompt files are produced at the end of Phase 5, after Claude.md
is committed. They are a named Phase 5 output — not generated at session
launch time.

**Path convention:**
sessions/S[N]_execution_prompt.md

One file per session defined in EXECUTION_PLAN.md. All files must be
committed before Phase 6 begins. This is a pre-condition for Phase 6,
not an in-session activity.

**What Has Already Been Built — mandatory for S02 onward:**

Each session prompt file contains a "What Has Already Been Built" paragraph.
This is written during Phase 5 while the plan is fresh — not reconstructed
later. The agent has no memory of prior sessions; this paragraph is the only
mechanism for session continuity.

- S01: write "This is the first session — repository scaffolded, no prior state."
- S02 onward: write one paragraph describing what the prior session left running,
  what invariants were verified, and what state the system is in at the start
  of this session.

**Trigger phrase:** "Produce session prompt files for this project"

**Gate:** All session prompt files committed to sessions/ before Phase 6
begins. PROJECT_MANIFEST.md updated with each file as PRESENT. Phase 6
may not begin until this gate passes — the launcher scripts depend on
prompt files existing at their declared paths.

**Conversation Quality Review:** Fires at the close of this phase gate — see Conversation Quality Review section.

For enhancement session prompt files, the path convention is:
sessions/SPRINT-NNN/ENH-NNN/S[N]_execution_prompt.md
The same What Has Already Been Built requirement applies.

---

## Claude.md Conventions

### Location and Root Stub Pattern

Claude.md is a mandatory artifact in `docs/` — not at repo root.

A one-line root stub is required at repo root as a CC tool-compatibility shim:
```
See docs/Claude.md
```

The stub must be registered in PROJECT_MANIFEST.md with the note:
"Tool-compatibility shim — not authoritative content."
The stub is not a content document. CC must not treat it as authoritative.

### Changelog Blocks on Versioned Docs

ARCHITECTURE.md, INVARIANTS.md, DATA_QUALITY_MANIFEST.md, and Claude.md all carry
a standardised changelog table immediately below the title line:

```markdown
## Changelog
| Version | Date | Author | Change |
|---|---|---|---|
| v1.0 | [date] | [engineer] | Greenfield — Initial |
```

For Claude.md already at a later version: populate the table to reflect actual history.
Earlier versions not recoverable from artifacts noted as:
"Pre-DataGrokr migration; history in git log."

### Frozen Banner on EXECUTION_PLAN.md

After Phase 8 sign-off, EXECUTION_PLAN.md receives a frozen banner immediately
after the title line:

```markdown
> **FROZEN** — This document is sealed as of [date] (Phase 8 sign-off,
> S9 complete). No modifications are permitted. All future enhancement
> planning uses `enhancements/ENH-NNN_EXECUTION_PLAN.md`.
```

---

## Claude.md Schema

A valid Claude.md contains exactly five sections in this order:

### Section 1 — System Intent
Two to three sentences. What the system does, what it does not do,
what success looks like.

### Section 2 — Hard Invariants
Numbered list. Every GLOBAL invariant from INVARIANTS.md, full text
verbatim, with IC-N reference. Every entry in this format:
  IC-N: [full invariant statement]
  This is never negotiable.

The CQ-001 complexity invariant is mandatory in this section
regardless of authoring mode. Verbatim text:
  "Each function, method, or handler must have a single stateable
   purpose. Conditional nesting exceeding two levels is a structural
   violation — refactor before proceeding. This is never negotiable."

Maximum five GLOBAL invariants in this section, plus the CQ-001
complexity invariant. The CQ-001 invariant does not consume an
engineer slot.

### Section 3 — Scope Boundary
Exact files the AI is permitted to create or modify in this session.
M-NNN references where graph artifacts are present. File paths where
graph artifacts are absent (greenfield pre-Phase 8). Out-of-scope
files explicitly listed.

### Section 4 — Fixed Stack
Exact technologies, versions, dependencies, environment variable
names. Anything not listed, the AI selects.

### Section 5 — Rules
The three structural rules verbatim per pbvi_core.md.

### Frontmatter
Claude.md must carry a frontmatter block with:
  - version: v1.0 (or later, per amendments)
  - METHODOLOGY_VERSION: [PBVI version used to author this Claude.md]
  - source: [PBVI-009 brownfield onboarding | PBVI Phase 5 greenfield |
             Sprint Claude.md amendment]
  - frozen: true (after generation)

---

## Phase 6 — Build Sessions

**Setup requirement — before the first build session begins:**

Copy `SKILL.md` from the DG-Forge `dg_os` GitHub repository into your project's
`.claude/` directory. The `dg_os` repository version is the source of truth.
Never edit the local copy directly.

### Phase 6 Pre-Build Validation

**When this runs:** At the very start of every build session — first session of an enhancement, every subsequent session, every resumed session after a block. It is not skipped on continuation; the schema and interpretation can drift.

**Inputs CC reads:**
- `Claude.md` (project root)
- `discovery/ID_REGISTRY.md` (must exist if the system is brownfield-onboarded or post-Phase 8 greenfield)
- `discovery/SYSTEM_GRAPH.json` (if available)
- `discovery/DOMAIN_MODEL.json` (if available)
- The current task or first task in the session execution plan

```
PHASE 6 PRE-BUILD VALIDATION — STEP A: CLAUDE.MD SCHEMA

Read Claude.md.

Check 1 — Section structure:
  - Section 1: System Intent — PRESENT / MISSING
  - Section 2: Hard Invariants — PRESENT / MISSING
  - Section 3: Scope Boundary — PRESENT / MISSING
  - Section 4: Fixed Stack — PRESENT / MISSING
  - Section 5: Rules — PRESENT / MISSING

Check 2 — Methodology anchor:
  - METHODOLOGY_VERSION recorded in Claude.md frontmatter or
    changelog: PRESENT / MISSING
  - METHODOLOGY_VERSION matches loaded skill version:
    MATCH / MISMATCH (warning, not blocker per FW-001)

Check 3 — Mandatory invariant:
  - CQ-001 complexity invariant present in Section 2 verbatim:
    "Each function, method, or handler must have a single stateable
     purpose. Conditional nesting exceeding two levels is a structural
     violation — refactor before proceeding. This is never negotiable."
    PRESENT / MISSING

Check 4 — ID reference resolution (only if ID_REGISTRY.md exists):
  Scan Claude.md Sections 2 and 3 for any of these patterns:
    - M-NNN (module IDs)
    - IC-N or IC-NN (invariant IDs)
    - IP-NNN (integration point IDs)
    - E-NNN (entity IDs)

  For each ID found, look it up in ID_REGISTRY.md:
    Match: VALID
    No match: STALE-OR-INVALID

If ID_REGISTRY.md does not exist (greenfield pre-Phase 8):
  Mark Check 4 as N-A.
  Record in session log that Phase 6 entered without graph backing.

OUTPUT — SCHEMA VALIDATION RESULT
| Check | Status | Notes |
|---|---|---|
| Section 1: System Intent | PRESENT / MISSING | |
| Section 2: Hard Invariants | PRESENT / MISSING | |
| Section 3: Scope Boundary | PRESENT / MISSING | |
| Section 4: Fixed Stack | PRESENT / MISSING | |
| Section 5: Rules | PRESENT / MISSING | |
| METHODOLOGY_VERSION | PRESENT / MISSING / MISMATCH | |
| CQ-001 complexity invariant | PRESENT / MISSING | |
| ID references resolved | ALL VALID / [N] STALE-OR-INVALID / N-A | [list invalid] |

VERDICT:
  PASS — all checks PRESENT or VALID, METHODOLOGY_VERSION present.
         Continue to Step B.
  WARN — METHODOLOGY_VERSION MISMATCH only.
         Record in session log; continue to Step B.
  HALT — any section MISSING, CQ-001 MISSING, or any STALE-OR-INVALID ID.
         Session does not proceed. Engineer must amend Claude.md or
         refresh BCE artifacts before re-invocation.
         Output: PRE-BUILD-PAUSED (HALT — schema invalid). Stop session.
```

```
PHASE 6 PRE-BUILD VALIDATION — STEP B: INTERPRETATION CONFIRMATION

Schema validation passed (or WARN-only). Now produce CC's interpretation
of the contract.

Read:
- Claude.md (full)
- The current task or first task in the session execution plan
- If SYSTEM_GRAPH.json present: query the subgraph for entry point modules
  declared in Claude.md Section 3 (Scope Boundary) using bce_core.md
  Section 16 mechanics at depth 2

Produce three statements:

1. MODULES I WILL MODIFY
   List M-NNN IDs (or file paths if pre-graph) that this session will
   modify. Drawn from Claude.md Scope Boundary and the first task.

2. INVARIANTS I WILL RESPECT
   List IC-N IDs with their full statement text. Drawn from Claude.md
   Hard Invariants (every GLOBAL invariant) plus any TASK-SCOPED
   invariants that apply to the modules in (1).

3. BLAST RADIUS
   In scope: [explicit file list, M-NNN list]
   Out of scope: [explicit file list — files CC will NOT touch]
   Integration points touched: [IP-NNN list, or "none"]
   Entities affected: [E-NNN list, or "none" or "N-A — no DOMAIN_MODEL.json"]

OUTPUT — INTERPRETATION CONFIRMATION
[The three statements as a structured block]

ENGINEER REVIEW PROMPT
Engineer reviews the three statements. Engineer responds with one of:
  - CONFIRMED — interpretation is correct; proceed to first task.
  - MODULES-WRONG — CC's modules list disagrees with intent;
                    return to planning, amend Claude.md or task.
  - INVARIANTS-WRONG — CC's invariants list is incomplete or incorrect;
                       return to planning, amend Claude.md.
  - BLAST-RADIUS-WRONG — CC's blast radius is wider or narrower than
                         intended; return to planning, amend scope.

If CONFIRMED: log the interpretation in the session log and proceed.
If any -WRONG response: session does not proceed to first task.
                       Engineer halts and returns to planning.
                       Resumption requires fresh Claude.md amendment
                       and re-running Steps A and B.
                       Output: PRE-BUILD-PAUSED (WRONG). Stop session.
```

**Re-run behaviour:** On resumption after CONFIRMED, Template 2B Step 0 reads the session log. If CONFIRMED is already recorded from the current session, Step 0 skips the HUMAN GATE and proceeds directly to the scope boundary and first task.

**Session log entry (existing artifact, extended):**

The session log gains a new Pre-Build Validation block at the top, before the Tasks table — see Template 1 in pbvi_templates.md.

### Execution Modes

Build sessions operate in one of two modes. Mode is declared in the session log at
session start. Neither mode is superior — choose based on project context.

**Manual mode:** Engineer runs CC task by task. Prediction statements are written
before each verification command. CC Challenge output is presented to the engineer
for accept/reject decisions on each gap. Used for external and client-facing
deliverables where human understanding at every step is required.

**Autonomous mode:** Engineer issues a single session execution prompt. CC executes
all tasks sequentially without pausing between tasks (unless a human gate is
explicitly marked in EXECUTION_PLAN.md). No prediction discipline. CC Challenge
runs autonomously — CC makes the determination and proceeds without engineer input.
If any verification command fails, CC stops immediately — no retry — and outputs a
SESSION BLOCKED summary. Used for internal projects where sequential throughput
matters more than step-by-step human verification.

**Task Prompt Immutability (Autonomous mode):**

The task prompt in EXECUTION_PLAN.md is a contract, not a starting point.
CC executes it exactly as written. The following are not permitted:

- Extending the task beyond its stated scope
- Adding functionality believed to be needed but not specified
- Fixing adjacent issues encountered during execution
- Improving code outside the task boundary

The test: if the task prompt does not explicitly require it, do not build it.

If something broken or missing is encountered outside the task scope: record it
in the Out of Scope Observations table in SESSION_LOG.md and continue. Do not
fix it. Do not use it to justify extending the task.

This rule has no exceptions. A task that passes verification but exceeded its
scope is not a complete task — it is an undeclared change.

### Git Conventions

| Rule | Format |
|---|---|
| Branch name | `session/s[n]_<short_desc>` e.g. `session/s02_api` |
| Commits | One commit per task — never batch multiple tasks into one commit |
| PR target | Session branch → main after session integration check passes |

Create the branch before any task work begins. Never commit to main directly.

**Commit message format — mandatory for all Autonomous mode commits:**
[S][N].[TASK_N] — [Task Name]: [one-line summary]
Scope: within Claude.md boundary — YES
Files: [list every file created or modified in this task]
Invariants touched: [INV-XX list — or NONE]
Pre-commit declaration: recorded in VERIFICATION_RECORD

Scope field must be YES. If any file is outside the Claude.md Scope Boundary,
do not commit — output SCOPE VIOLATION and stop the session.

This format applies to Autonomous mode. Manual mode retains the existing
one-line format: `[S][N].[TASK_N] — [Task Name]: [one-line summary]`

### Per-Task Execution Order

**Manual mode — order is strict:**
1. Read the task from `EXECUTION_PLAN.md`
2. Create/update Verification Record — pre-populate Task ID, Task Name, Scenario,
   Expected from EXECUTION_PLAN.md. Leave Result, Prediction Statement, CC Challenge
   Output, BCE Impact, UI Tests column, and all Verdict checkboxes blank.
3. Run the CC task prompt
3b. UI test writing — PBVI-011, conditional on task carrying a UI test spec
   (EXECUTION_PLAN.md item 7). After implementation is complete and before running
   the verification command, implement the Playwright test assertions specified in
   the task's UI test spec.
   - Write tests to the file path specified in the UI test spec (ui_tests/[screen-slug].spec.ts).
   - One describe block per screen. One it() per assertion.
   - Tests must pass with the current implementation before the task is considered
     complete. If a test cannot pass because the feature is intentionally incomplete
     (e.g. a modal that opens from a screen built in a later session), mark the test
     as todo() with a one-line explanation referencing the future task.
   - Add the test file to the task commit — it is NOT a separate commit.
   - Engineer reviews test assertions before the verification command runs.
   - Record the UI Tests column in VERIFICATION_RECORD.md: `WRITTEN — N assertions`
     or `TODO(N) — reason`.
4. **Engineer writes prediction statement** before running any verification command
5. Run the verification command and evaluate test cases
6. CC Challenge — present gaps to engineer; engineer accepts (add test case, run
   immediately, record result) or rejects (document reason)
7. Record BCE Impact
8. PASS verdict — all checkboxes confirmed
9. Commit: `[S][N].[TASK_N] — [Task Name]: [one-line summary]`
10. Update session log immediately

**Autonomous mode — order per task:**
1. Read the task from `EXECUTION_PLAN.md` — execute the task prompt exactly
   as written. Task Prompt Immutability applies — see Execution Modes above.
2. Create/update Verification Record — pre-populate Task ID, Task Name, Scenario,
   Expected. Omit Prediction Statement section entirely (do not leave blank).
   For UI-touching tasks, leave the UI Tests column blank.
3. Run the CC task prompt
3b. UI test writing — PBVI-011, conditional on task carrying a UI test spec
   (EXECUTION_PLAN.md item 7). After implementation is complete and before running
   the verification command, implement the Playwright test assertions specified in
   the task's UI test spec.
   - Write tests to the file path specified in the UI test spec (ui_tests/[screen-slug].spec.ts).
   - One describe block per screen. One it() per assertion.
   - Tests must pass with the current implementation before the task is considered
     complete. If a test cannot pass because the feature is intentionally incomplete,
     mark the test as todo() with a one-line explanation referencing the future task.
   - Add the test file to the task commit — it is NOT a separate commit.
   - Record the UI Tests column in VERIFICATION_RECORD.md: `WRITTEN — N assertions`
     or `TODO(N) — reason`. For tasks without a UI test spec, write `N/A`.
4. Run the verification command and evaluate test cases
5. If verification fails: invoke FAILURE HANDLING (see Session Execution Prompts).
   Do not proceed to step 6.
6. Run deterministic file boundary check:
   Run: git diff --name-only HEAD
   Compare the output against the permitted file list in the session execution
   prompt Scope Boundary section. If any file is outside the permitted list:
   invoke SCOPE VIOLATION handling. Do not proceed to step 7.
7. Output pre-commit declaration:

   PRE-COMMIT DECLARATION — [Task ID]
   -----------------------------------
   Files modified:     [git diff --name-only HEAD output]
   Functions added:    [list or NONE]
   Functions modified: [list or NONE]
   Functions deleted:  [list or NONE]
   Schema changes:     [list or NONE]
   Config changes:     [list or NONE]

   Everything above is within the task prompt scope: YES / NO

   If NO on any item: invoke SCOPE VIOLATION handling. Do not proceed to step 8.
   Write the declaration to the Verification Record.

8. Challenge Agent invocation — run the independent challenge agent:
   ./tools/challenge.sh S[SESSION_NUMBER] [TASK_ID]
   The challenge agent receives only evidence artifacts — it has no access to
   this session's reasoning or build context.
   - If verdict is CLEAN: proceed to step 9.
   - If verdict is FINDINGS: invoke CHALLENGE FINDINGS handling.
     Do not proceed to step 9.
   Write the full challenge output to the Verification Record Challenge
   Agent Output section.
9. Record BCE Impact
10. Record Out of Scope Observations in SESSION_LOG.md if any items were noticed
    during this task that are outside scope. Do not act on them — record only.
11. PASS verdict — all checkboxes confirmed
12. Commit using mandatory scope declaration format (see Git Conventions)
13. Update session log immediately

### The Build Loop (per task)

1. Take CC prompt from EXECUTION_PLAN.md — use it exactly as written
2. Give it to Claude Code
3. **Read every generated file and test script before running anything**
4. Verify per mode (see Per-Task Execution Order above)
5. If verified: commit, update SESSION_LOG.md, move to next task
6. If failed (Autonomous): invoke FAILURE HANDLING — stop, do not fix, do not retry

**If CC makes a decision not covered in Claude.md — stop immediately.**
Return to Claude Desktop. Either re-prompt CC with tighter constraints,
or revise the planning artifact and produce a new Claude.md version.

**If a build session chat is becoming too long:** ask Claude Desktop for a
handoff prompt before continuing.

One task. One commit. No batching. No skipping.

---

## Template Integrity Rules — CRITICAL

These rules are non-negotiable. Claude must never violate them when generating templates.

### Fields That Must Always Be LEFT BLANK at creation

| Field | Why | Mode |
|---|---|---|
| Prediction statements | Core cognitive forcing function — engineers must form expectations before running commands. Pre-populating destroys the value. | Manual only — omit entirely in Autonomous |
| Verification results (PASS/FAIL) | Must reflect actual execution, never anticipated | Both |
| Scope decisions | Must be made by the engineer during the session | Both |
| Deviation observations | Must reflect what actually happened | Both |
| Session completion sign-off | Human gate — never pre-filled | Both |

**Prediction Statement rule (Manual mode):** Leave blank — engineer fills before running
any verification command. This is the methodology's primary cognitive enforcement mechanism.

**Prediction Statement rule (Autonomous mode):** Omit the section entirely from the
Verification Record. Do not leave it blank — a blank field implies it should be filled.
Removing it signals the section does not apply to this execution mode.

### Fields That May Be Pre-Populated

| Field | Source |
|---|---|
| Test case scenarios (Scenario column) | Copied from EXECUTION_PLAN.md |
| Expected outcomes (Expected column) | Copied from EXECUTION_PLAN.md |
| Invariant touch notes | Copied from EXECUTION_PLAN.md |
| Branch name, session name, task list | Known from plan |

**Rule of thumb:** If it requires running code or making a judgment after execution, leave it blank.

---


## Phase 7 — Verification

Verification is a human act. It cannot be delegated. No task is complete until
verified. No next task begins until the current one passes.

**Four questions to answer from the specification — not the implementation:**
- Q1: What does correct behaviour look like, precisely?
- Q2: What inputs or conditions would cause this to behave incorrectly?
- Q3: What did Claude assume that has not been confirmed? (This is the CC Challenge)
- Q4: Does this task touch an invariant? If yes, code review is required now.

**Code review for invariant-touching tasks — confirm all four:**
- The invariant condition is actually enforced in the code
- No code path bypasses the enforcement
- The enforcement is in the right place (not just present somewhere)
- Future additions cannot bypass it without explicitly removing the check

---

## Phase 8 — System Sign-Off

**Purpose:** Verify the fully assembled system against every invariant end to end,
then close out BCE artifacts. All sessions complete and merged. This phase produces
no new code.

Phase 8 has two distinct parts that apply to both greenfield and enhancement builds:

| Part | Greenfield | Enhancement |
|---|---|---|
| Part 1 — System Sign-Off | Invariant verification — identical for both | ← same |
| Part 2 — BCE Close-Out | Part 2A: BCE Adapter Pipeline | Part 2B: BCE Impact Log |

Both parts must complete before Phase 8 is done. The sign-off gate separates them —
Part 2 does not begin until Part 1 sign-off is complete. For enhancements, Part 1
sign-off artifact is tier-dependent (see Sign-Off Tier table in Part 1).

### Part 1 — System Sign-Off

**Steps in order — identical for greenfield and enhancement:**
1. Take each invariant in scope (see Sign-Off Tier below) in sequence.
   INVARIANTS.md is the authoritative registry for sign-off regardless of scope tag —
   both GLOBAL and TASK-SCOPED invariants are verified at Phase 8.
2. Run a system-level test against the fully assembled, running stack
3. Record PASS or FAIL for each invariant — in VERIFICATION_CHECKLIST.md (Tier 2/3)
   or in Verification Record verdicts (Tier 1)
4. Confirm architecture alignment: system matches ARCHITECTURE.md,
   no undocumented components exist
5. If any invariant fails: return to the relevant session, run the
   task-level PBVI loop, then return to sign-off
6. All invariants verified — sign off per tier
7. Regression suite assembly — collect the portable verification commands from all
   REGRESSION-RELEVANT and HARNESS-CANDIDATE tasks in EXECUTION_PLAN.md. Consolidate
   into a single runnable suite at `verification/REGRESSION_SUITE.sh`. Commit to repo.
   If a verification command is not portable, note it in the suite with the reason —
   do not silently omit it. This step is not optional and is not deferred.
8. Harness assembly — collect HARNESS-CANDIDATE commands from all HARNESS-CANDIDATE
   tasks in EXECUTION_PLAN.md. Assemble into `verification/HARNESS.sh` using Template 9
   (pbvi_templates.md). One section per invariant — assertion command, expected outcome,
   severity (CRITICAL or WARNING), and full invariant statement. Commit to repo alongside
   REGRESSION_SUITE.sh. If no HARNESS-CANDIDATE tasks exist, create a scaffold-only
   HARNESS.sh with no assertion sections and a comment noting none were classified.
   This step is not optional and is not deferred.
9. UI harness assembly (PBVI-011 — UI projects only, conditional on APPLICATION_SURFACE
   containing UI). For API_ONLY and BACKGROUND_SERVICE: skip entirely.

   Collect all Playwright test files from `ui_tests/`. Assemble
   `verification/UI_HARNESS.sh` using the template below. Commit to repo alongside
   HARNESS.sh and REGRESSION_SUITE.sh.

   If no `ui_tests/` files exist: create a scaffold-only UI_HARNESS.sh with a comment
   noting that no UI tests were produced. This is a process gap — note it in the
   Phase 8 sign-off record. This step is not optional and is not deferred.

   UI_HARNESS.sh template:
   ```bash
   #!/usr/bin/env bash
   # UI_HARNESS.sh — [PROJECT_NAME]
   # Generated by PBVI Phase 8 — UI Harness Assembly (PBVI-011)
   # Trigger: Phase 8 completion and on-demand only
   # Do not run at session end — Playwright requires browser runtime

   set -e

   echo "=== UI Harness — [PROJECT_NAME] ==="
   echo "Running Playwright test suite from ui_tests/"
   echo ""

   npx playwright test ui_tests/ --reporter=list

   EXIT_CODE=$?

   if [ $EXIT_CODE -eq 0 ]; then
     echo ""
     echo "=== UI HARNESS: PASS ==="
   else
     echo ""
     echo "=== UI HARNESS: FAIL — see output above ==="
   fi

   exit $EXIT_CODE
   ```

   **Trigger phrases:**
   - "Assemble UI harness" → Phase 8 step 9
   - "Run UI harness" → executes `verification/UI_HARNESS.sh`

   UI_HARNESS.sh does not run at session end — Playwright tests are slow and require
   a browser runtime. It runs at Phase 8 completion and on-demand only.

**Sign-off (greenfield):** Documented sign-off in VERIFICATION_CHECKLIST.md
required for customer deliverables and internal accelerators.
For enhancement sign-off tiers, see **pbvi_sprint.md**.

**After Part 1 sign-off:** Proceed to Part 2A (greenfield) or see pbvi_sprint.md (enhancement).

### Part 2A — BCE Close-Out (Greenfield)

**Purpose:** Build the system intelligence layer from the completed PBVI-governed system.
Runs after Part 1 sign-off. Uses the PBVI Adapter Pipeline (Path C). **Not optional** —
a greenfield build is not complete until all seven BCE artifacts are committed,
ANNOTATION_CHECKLIST.md P1 items are reviewed, and CD project files are updated.

**Inputs:** `docs/` (ARCHITECTURE.md, INVARIANTS.md, EXECUTION_PLAN.md, Claude.md),
`verification/` (VERIFICATION_CHECKLIST.md), source code (Stage 2).

**Step 1 — Stage 1 (CC):** Run the Stage 1 execution prompt from **BCE skill Section 10**.

**Human gate — mandatory before Stage 2:** Engineer reviews Stage 1 draft artifacts and
signs off. Stage 2 does not begin until this gate passes.

**Step 2 — Stage 2 (CC):** Run the Stage 2 execution prompt from **BCE skill Section 11**.
Where Stage 2 diverges from Stage 1: flag with STAGE-2-DIVERGENCE. Do not resolve silently.

**Step 3 — Stage 3 (CD):** Run the Stage 3 execution prompt from **BCE skill Section 12**.
Stage 3 produces ANNOTATION_CHECKLIST.md. P1 items must be reviewed and signed off before
Phase 8 is complete. P1 items that cannot be resolved immediately become sprint planning blockers.

**Step 4 — Commit sequence**

```bash
# Commit 1 — INTAKE_SUMMARY.md (prerequisite artifact, produced in Stage 1)
git add discovery/INTAKE_SUMMARY.md
git commit -m "Phase 8 BCE close-out: INTAKE_SUMMARY.md — Stage 1 prerequisite artifact"

# Commit 2 — five living extraction artifacts (completed in Stage 2)
git add discovery/TOPOLOGY.md
git add discovery/MODULE_CONTRACTS.md
git add discovery/INTEGRATION_CONTRACTS.md
git add discovery/INVARIANT_CATALOGUE.md
git add discovery/RISK_REGISTER.md
git add discovery/components/
git commit -m "Phase 8 BCE close-out: Stage 2 complete — five living extraction artifacts"

# Commit 3 — ANNOTATION_CHECKLIST.md (attestation artifact, produced at Stage 3)
git add discovery/ANNOTATION_CHECKLIST.md
git commit -m "Phase 8 BCE close-out: Stage 3 complete — ANNOTATION_CHECKLIST.md produced"

# Commit 4 — P1 sign-offs recorded in ANNOTATION_CHECKLIST.md
git add discovery/ANNOTATION_CHECKLIST.md
git commit -m "Phase 8 BCE close-out: P1 items reviewed and signed off"
```

**Step 5 — CD update gate**

Upload all seven BCE artifacts to the CD project for this system — INTAKE_SUMMARY.md,
the five living extraction artifacts, and ANNOTATION_CHECKLIST.md. This makes them
available to every future planning session. A stale CD project file produces stale
planning context.

This is a named step — not optional, not deferred.

---

**Phase 8 complete (greenfield) when:** all invariants verified,
VERIFICATION_CHECKLIST.md signed off, regression suite committed to
`verification/REGRESSION_SUITE.sh`, harness committed to `verification/HARNESS.sh`,
all seven BCE artifacts committed, ANNOTATION_CHECKLIST.md P1 items signed off,
CD project files updated.

**Phase 8 complete (UI projects — additional requirements, PBVI-011):** When
APPLICATION_SURFACE contains UI:
- UI_HARNESS.sh assembled and committed to `verification/`
- UI_HARNESS.sh run successfully — all tests pass, or todo() items documented in
  the Phase 8 sign-off record with reasons
- `ui_tests/` directory registered in PROJECT_MANIFEST.md (Non-Standard Registered
  Directories) with Status: PRESENT

For enhancement completion criteria see **pbvi_sprint.md**.

---

## Brownfield Onboarding Procedure (PBVI-009)

### Procedure Overview

This procedure runs **once per brownfield system**. It bridges BCE extraction and sprint governance by deriving the PBVI planning artifact set (`docs/ARCHITECTURE.md`, `docs/INVARIANTS.md`, `Claude.md`) from a completed BCE artifact set.

**This is not a PBVI phase and not a PBVI path.** It does not recur. It does not overlap with greenfield Phases 1–8. After completion, the system enters the standard sprint path with no special treatment.

```
PRECONDITION: BCE extraction complete (Stages 1–3, six living artifacts).
              SYSTEM_GRAPH.json and DOMAIN_MODEL.json may or may not be
              present — Step 1 evaluates and remediates.
              ↓
Step 1 — BCE Completeness Check (CD)
              ↓ (gate: completeness PASS or READY-WITH-CAVEATS)
Step 2 — Derive ARCHITECTURE.md (CD)
              ↓ (gate: engineer sign-off on interpretation)
Step 3 — Derive and Enrich INVARIANTS.md (CD)
              ↓ (gate: engineer sign-off, GLOBAL/TASK-SCOPED classified, ≤5 GLOBAL)
Step 4 — Generate Claude.md (CD)
              ↓ (gate: standard Phase 5 freeze)
Step 5 — Sprint-Ready Declaration (CD + engineer)
              ↓
SYSTEM IS SPRINT-READY — first enhancement brief can enter enhancements/backlog/
              ↓
Sprint path takes over from here
```

**No build sessions are created during onboarding.** Onboarding is a planning artifact derivation procedure, not a build procedure. `sessions/` directory remains empty until the first sprint produces `S1_execution_prompt.md`.

---

### Step 1 — BCE Completeness Check

```
Tool: CD
Trigger phrases:
- "Run Step 1 of brownfield onboarding"
- "Run BCE completeness check for brownfield onboarding"
Inputs the skill loads:
- discovery/ artifacts (auto-discovered)
- bce_core.md cross-reference for completeness check criteria
Human gate: Engineer reviews BCE COMPLETENESS REPORT verdict before invoking Step 2.
Output: BCE COMPLETENESS REPORT block + verdict + ONBOARDING_LOG.md Section 1 entries.
```

**Purpose:** Confirm BCE is complete enough to derive PBVI planning artifacts. Identify and remediate gaps — particularly missing `SYSTEM_GRAPH.json` or `DOMAIN_MODEL.json` — before onboarding proceeds.

**Checks performed:**

| Check | Pass criterion | Failure handling |
|---|---|---|
| All six living BCE-C artifacts present | All files exist in `discovery/` | STOP. Report missing artifacts. Direct engineer to complete BCE Stage 1/2/3. |
| `INTAKE_SUMMARY.md` Stage 3 sign-off complete | "STAGE-3-COMPLETE" marker present and dated | STOP. Direct engineer to complete BCE Stage 3 sign-off. |
| `SYSTEM_GRAPH.json` present | File exists, parses as valid JSON | If absent: instruct engineer to run BCE Stage 3 graph construction prompt against existing BCE-C artifacts. Onboarding pauses. Re-invoke Step 1 when complete. |
| `DOMAIN_MODEL.json` present OR formally absent-by-design | File exists, OR engineer confirms no structural data layer | If absent and structural data layer exists: instruct engineer to run BCE-005 Session F. Onboarding pauses. If absent and no structural data layer: engineer confirms absent-by-design; continue with note in ONBOARDING_LOG.md Section 1. If engineer defers Session F: continue, record deferral, flag PBVI-010 fidelity caveat. |
| `ID_REGISTRY.md` present | File exists | If absent: STOP. Direct engineer to run BCE-005 Session F03 close-out. |
| `ANNOTATION_CHECKLIST.md` P1 items reviewed | All P1 items show SIGNED-OFF or RESOLVED status | WARN. Engineer may proceed at risk; unresolved P1 items become onboarding caveats recorded in ONBOARDING_LOG.md. |
| BCE-S signal artifacts (if present) | If `discovery/signal/` exists, `SIGNAL_GAPS.md` is signed | WARN, not STOP. BCE-S enrichment is optional for onboarding. |
| BCE artifact freshness | `INTAKE_SUMMARY.md` Stage 3 sign-off date is within three months | WARN. Engineer judgment on whether to refresh BCE before onboarding. |

**Output verdict:** READY / READY-WITH-CAVEATS / BLOCKED-PENDING-BCE / BLOCKED-PENDING-SESSION-F / BLOCKED-PENDING-GRAPH-CONSTRUCTION.

If any BLOCKED variant: stop here. Onboarding does NOT run BCE work itself — it bounces back to `bce_core.md`.

**Human gate:** Engineer reviews the BCE COMPLETENESS REPORT and confirms onboarding may proceed. Caveats and deferrals are recorded verbatim in `ONBOARDING_LOG.md` Section 1.

---

### Step 2 — Derive ARCHITECTURE.md

```
Tool: CD
Trigger phrases:
- "Run Step 2 of brownfield onboarding"
- "Derive ARCHITECTURE.md for brownfield onboarding"
Inputs the skill loads:
- TOPOLOGY.md, MODULE_CONTRACTS.md, INTEGRATION_CONTRACTS.md
- SYSTEM_GRAPH.json
- DOMAIN_MODEL.json (if present)
- RISK_REGISTER.md
- discovery/signal/SYSTEM_INTENT.md (if present)
Human gate: Engineer reviews and signs off ARCHITECTURE.md before invoking Step 3.
              Interpretive divergences logged in ONBOARDING_LOG.md Section 2.
Output: docs/ARCHITECTURE.md draft (1–3 pages, interpretive) + ARCH-DIV-NNN entries.
```

**Purpose:** Produce a thin, interpretive `docs/ARCHITECTURE.md` that captures what BCE alone cannot — narrative, inferred design decisions, debt context, success/failure framing. **It is not a fact rehash of BCE artifacts.**

**What CD produces** — `docs/ARCHITECTURE.md` with these sections and no others:

1. **System Identity** — 1-paragraph high-level statement drawn from BCE-S SYSTEM_INTENT.md if present, otherwise composed from BCE-C artifacts and engineer knowledge.
2. **Source of Record** — table pointing to authoritative BCE artifacts for each factual concern. This document does not duplicate them.
3. **Layer Boundary Rationale** — interpretive narrative (2–5 paragraphs). For each significant layer boundary in TOPOLOGY.md: why does it exist? What is at risk if crossed?
4. **Implicit Design Decisions** — patterns that BCE surfaced implying intentional architectural choices. Each as IDD-NNN with pattern observed, inferred decision, alternative interpretation, engineer assessment (CONFIRMED / PROBABLE / UNCERTAIN).
5. **Architectural Debt Narrative** — contextualised reading of RISK_REGISTER.md. Not a re-listing of risks — the trajectory and cause narrative.
6. **Architecture Health and Failure Modes** — what architectural success and failure look like at the boundary level. Seeds GLOBAL invariants in INVARIANTS.md.
7. **Open Architectural Questions** — genuine unknowns. Each becomes a candidate ANNOTATION_CHECKLIST.md item.
8. **Engineer Sign-Off** block.

**Length target:** 1–3 pages of interpretive content plus pointer table. If CD is producing more, it is rehashing — reduce content and increase pointer references.

**Divergence log:** Each interpretive correction is recorded as:

```
ARCH-DIV-NNN
Source statement: [what ARCHITECTURE.md inferred or asserted]
Engineer correction: [what operational knowledge says about the interpretation]
Resolution: [how ARCHITECTURE.md was updated]
```

**Human gate:** Engineer signs off `docs/ARCHITECTURE.md`. Sign-off recorded in `ONBOARDING_LOG.md` Section 2.

---

### Step 3 — Derive and Enrich INVARIANTS.md

```
Tool: CD
Trigger phrases:
- "Run Step 3 of brownfield onboarding"
- "Derive INVARIANTS.md for brownfield onboarding"
Inputs the skill loads:
- INVARIANT_CATALOGUE.md
- signed docs/ARCHITECTURE.md (Sections 3, 4, 6)
- discovery/signal/BUSINESS_INVARIANTS.md (if present)
Human gate: Engineer adjudicates each candidate. Five-GLOBAL ceiling enforced.
              Sign-off blocked if ceiling violated.
Output: docs/INVARIANTS.md draft + adjudication record in ONBOARDING_LOG.md Section 3.
```

**Purpose:** Propose `INVARIANTS.md` from two sources simultaneously and let the engineer promote / classify / reject.

**CD's task — dual-source proposal:** For each candidate invariant, declare:

```
INVARIANT CANDIDATE
Statement:        [full invariant statement]
Source:           CATALOGUE (IC-NNN) | ARCHITECTURE | BUSINESS_INVARIANTS | INTERSECTION
Origin reference: [IC-NNN | section in ARCHITECTURE.md | BI-NNN | combination]
Category:         STRUCTURAL | DATA | DOMAIN
Proposed scope:   GLOBAL | TASK-SCOPED
Failure mode:
  - Violation observable state: [what is observable when this fails]
  - Detection point:            [where in the system the violation surfaces]
  - Blast radius:               [scope of impact on violation]
Rationale:        [why this invariant matters; one paragraph]
Confidence:       HIGH | MEDIUM | LOW
```

The Failure Mode Draft format is mandated per PBVI-008. Every invariant carries one regardless of authorship mode.

**Engineer adjudication per candidate:**

```
ENGINEER DECISION
[ ] ACCEPT-AS-PROPOSED
[ ] ACCEPT-WITH-MODIFICATION — modified statement: [...]
[ ] RECLASSIFY — change scope to GLOBAL | TASK-SCOPED, rationale: [...]
[ ] REJECT — rationale: [...]
[ ] DEFER — return to invariant after first sprint, rationale: [...]
```

**Five-GLOBAL ceiling — hard enforcement:** If proposed GLOBAL invariants exceed five, the engineer must either promote some to TASK-SCOPED, merge related invariants, or defer some. CD enforces the ceiling explicitly. The engineer cannot sign off `INVARIANTS.md` with more than five GLOBAL invariants. There is no override.

**Before sign-off, CD emits this notice verbatim:**

> "A newly onboarded brownfield system may produce a thin INVARIANTS.md if operational knowledge is limited. This is expected and honest. Invariant sets enrich through the first few sprints as operational knowledge accumulates. Thin is better than fabricated. Do not invent invariants to fill perceived gaps."

**Human gate:** Engineer signs off `docs/INVARIANTS.md`. Sign-off recorded in `ONBOARDING_LOG.md` Section 3.

---

### Step 4 — Generate Claude.md

```
Tool: CD
Trigger phrases:
- "Run Step 4 of brownfield onboarding"
- "Generate Claude.md for brownfield onboarding"
Inputs the skill loads:
- signed docs/ARCHITECTURE.md
- signed docs/INVARIANTS.md
Human gate: Engineer reviews and confirms Claude.md generation.
              Standard Phase 5 freeze rules apply.
Output: Claude.md v1.0 (frozen) + ONBOARDING_LOG.md Section 4 entry.
```

**Purpose:** Produce the frozen execution contract using the standard PBVI Phase 5 generation procedure. The inputs are different (interpreted rather than designed) but the generation step is identical.

**Required sections** (unchanged from greenfield Phase 5): System Intent, Hard Invariants (all GLOBAL + CQ-001 complexity invariant), Architecture Summary, Build Mode, Methodology Anchors.

**Brownfield-specific changelog entry inside Claude.md:**

```
| Version | Date | Source | Summary |
| v1.0 | [date] | PBVI-009 brownfield onboarding | Generated from BCE-derived ARCHITECTURE.md and INVARIANTS.md. Source system: [system name]. METHODOLOGY_VERSION: [version]. Onboarding signed off by [engineer name] on [date]. |
```

**Claude.md is FROZEN on generation.** Version is v1.0. Subsequent changes follow standard sprint amendment rules per `pbvi_sprint.md`.

**Human gate:** Engineer reviews and confirms Claude.md generation. Sign-off recorded in `ONBOARDING_LOG.md` Section 4.

---

### Step 5 — Sprint-Ready Declaration

```
Tool: CD
Trigger phrases:
- "Run Step 5 of brownfield onboarding"
- "Declare system sprint-ready"
Inputs the skill loads:
- All artifacts produced in Steps 1–4
Human gate: Engineer signs the final attestation in ONBOARDING_LOG.md Section 5.
Output: PROJECT_MANIFEST.md, enhancements/REGISTRY.md, sprint-ready confirmation block.
```

**Purpose:** Initialise project governance artifacts and declare the system sprint-ready.

**5a — Initialise or update `PROJECT_MANIFEST.md`** with ONBOARDING_SOURCE, ONBOARDING_DATE, ONBOARDING_LOG fields (see Project Initialisation section), INVARIANT_AUTHORSHIP_MODE = GOVERNED, Core Documents table populated, BCE artifact set noted.

**5b — Initialise `enhancements/REGISTRY.md`** — empty registry, no enhancements yet.

**5c — Verify standard repository structure** — `docs/`, `discovery/`, `enhancements/`, `enhancements/backlog/`, `enhancements/REGISTRY.md`, `verification/` (empty), `sessions/` (empty), `tools/`. Missing directories are created. No files are produced beyond what Steps 1–4 generated.

**5d — Sprint-ready declaration:** CD outputs:

```
PBVI-009 BROWNFIELD ONBOARDING COMPLETE
---------------------------------------
System:              [system name]
Onboarding date:     [date]
Engineer:            [name]
METHODOLOGY_VERSION: [version]

Planning artifacts produced:
  ✓ docs/ARCHITECTURE.md v1.0 (interpretive layer over BCE)
  ✓ docs/INVARIANTS.md v1.0 (dual-source: catalogue + architecture)
  ✓ Claude.md v1.0 (frozen)

Project artifacts initialised:
  ✓ PROJECT_MANIFEST.md
  ✓ enhancements/REGISTRY.md (empty)
  ✓ Standard repository structure

Onboarding attestation:
  ✓ discovery/ONBOARDING_LOG.md (signed)

System status: SPRINT-READY

Next step: First enhancement brief enters enhancements/backlog/.
Sprint path takes over from here.
```

**Human gate:** Engineer signs the final attestation in `ONBOARDING_LOG.md` Section 5. This freezes `ONBOARDING_LOG.md` — it is append-only during onboarding and frozen on Section 5 sign-off.

---

### Edge Cases

- **BCE-004 absent — no SYSTEM_GRAPH.json:** Step 1 emits BLOCKED-PENDING-GRAPH-CONSTRUCTION. Engineer runs BCE Stage 3 graph construction prompt against existing BCE-C artifacts (no new code examination required). Re-invoke Step 1 when complete.
- **BCE-005 absent — no DOMAIN_MODEL.json, data layer present:** Step 1 emits BLOCKED-PENDING-SESSION-F. Engineer runs BCE-005 Session F (F01 mandatory, F02 conditional, F03 mandatory). Re-invoke Step 1 when complete.
- **No structural data layer — DOMAIN_MODEL.json correctly absent:** Step 1 emits READY-WITH-CAVEATS. Engineer confirms absent-by-design. ONBOARDING_LOG.md records confirmation. ARCHITECTURE.md Source of Record notes "DOMAIN_MODEL.json — N/A: no structural data layer".
- **Engineer defers Session F despite data layer present:** Step 1 emits READY-WITH-CAVEATS. Onboarding proceeds. PBVI-010 will operate at reduced fidelity until Session F is completed.
- **BCE over three months old — code has drifted:** Step 1 emits freshness WARN. Engineer judgment on BCE refresh. PBVI-009 does not run BCE work.
- **BCE-C complete, no BCE-S signal:** Onboarding proceeds. BCE-S is optional. ARCHITECTURE.md Section 1 and Section 4 will carry lower confidence levels.
- **ARCHITECTURE.md keeps getting bloated:** Decision 4 violation. CD must reduce content and increase pointer references. Engineer review explicitly checks page count and rejects bloat.
- **Engineer attempts to rubber-stamp Steps 2 and 3:** Sign-off blocks are mandatory. CD refuses to proceed without explicit sign-off in the log. No "approve all" flag.
- **More than five GLOBAL invariants emerge:** Five-GLOBAL ceiling is hard. CD presents three options: promote to TASK-SCOPED, merge, or defer. No sign-off until ≤5 GLOBAL.
- **INVARIANTS.md ends up thin (one or two GLOBAL):** Acceptable. Honest constraint applies. ONBOARDING_LOG.md Section 3 records thin start and notes enrichment expected through early sprints.
- **Pre-existing ad-hoc planning artifacts in repo:** PBVI-009 produces fresh `docs/ARCHITECTURE.md`. Pre-existing documents are renamed to `_legacy_ARCHITECTURE.md` and noted in ONBOARDING_LOG.md Section 2 as divergence references.

---

### What Is Deliberately Absent

| Artifact | Why absent |
|---|---|
| `EXECUTION_PLAN.md` | No build scope yet. First execution plan comes from first enhancement brief. |
| `sessions/` content | No build sessions during onboarding. |
| `verification/HARNESS.sh` | No invariant assertion harness until first sprint produces HARNESS-CANDIDATE tasks. |
| `verification/REGRESSION_SUITE.sh` | Same as above — populated by first sprint. |
| `PHASE4_GATE_RECORD.md` | No Phase 4 Design Gate during onboarding — no design under review. |

**Critical:** Do not scaffold empty placeholder files for "consistency with greenfield." Absence is meaningful — these artifacts genuinely do not exist until the first sprint.

---

## The CC Challenge

After completing a task's verification commands, ask Claude Code:

> "What did you not test in this task?"

For each gap identified: decide whether to accept (add a test case) or reject (document reason).
Record the full exchange in the CC Challenge Output section of the verification record.

This step is mandatory for every task. Its absence is a process violation.

---

## Human Accountability Gates

| Gate | Trigger | What Must Happen Before Proceeding |
|---|---|---|
| Architecture selection | End of Phase 1 Explore | Engineer chooses architecture — not Claude |
| Session start | Before any task in a new session | Branch created, previous session integration check passed |
| Task commit | After each task | Verification command passed, prediction + result recorded |
| Session completion | End of session | All tasks committed, integration check passed, PR raised, sign-off given |
| Phase transition | Moving to next session | Previous session PR merged to main |

Claude may not declare a gate passed. Only the engineer signs off.

---

## Session Execution Prompts

Phase 5 produces `sessions/S[N]_execution_prompt.md` for each session (Template 2B
from pbvi_templates.md). This file is the complete execution spec — it carries
TASK-LEVEL VERIFICATION, all handling blocks, scope boundary, and stop conditions.
Load pbvi_templates.md to generate it.

**Autonomous mode:** load the session prompt file as a project file in CC alongside
Claude.md. Trigger: "Run session [N] autonomously". Grant file permissions when CC
prompts interactively. `./tools/launch.sh` is an optional automation wrapper — it
does not handle interactive permission prompts reliably.

**Manual mode:** load the session prompt file as a project file in CC alongside
Claude.md. Trigger: "Begin session S[N]" or "Start session S[N]".

If a session is interrupted by a BLOCKED stop, use the Resume Prompt below — not
the session prompt file, which would re-run completed tasks.

---

### Autonomous Mode — Resume Prompt

**Tool:** CC
**Trigger phrases:**
- "Resume autonomous session"
- "Resume after BLOCKED"
- "Continue autonomous session [N]"

Use this prompt only after a BLOCKED stop in an Autonomous mode session. Do not
use the full Session Execution Prompt to resume — it will re-run completed tasks.

Engineer supplies three values before running this prompt:
- [SESSION_NUMBER] — same session number as the blocked session
- [RESUME_TASK_ID] — the task ID shown in the SESSION BLOCKED summary
- [BLOCKING_ISSUE_RESOLUTION] — one line describing what was fixed

```
You are resuming Session [SESSION_NUMBER] of this PBVI project after a BLOCKED stop.

Before taking any action, read the following in order:
1. Claude.md — scope boundaries and invariants
2. EXECUTION_PLAN.md — full task list for Session [SESSION_NUMBER]
3. sessions/SESSION_LOG_S[SESSION_NUMBER].md — current session state
4. sessions/VERIFICATION_RECORD_S[SESSION_NUMBER].md — current verification state

STATE VERIFICATION
Before proceeding, confirm the following:
- Read the session log and identify all tasks with Status = Completed.
  For each: confirm its recorded commit hash exists on branch
  session/[SESSION_NUMBER]-[session-slug].
- Confirm the task with Status = BLOCKED matches [RESUME_TASK_ID].
- If any completed task has no matching commit on the branch, or if the BLOCKED
  task does not match [RESUME_TASK_ID]: stop immediately and report the
  inconsistency. Do not attempt to resolve it.

If state verification passes, add a RESUMED marker to the session log immediately:
- Update the Resumed Sessions table in SESSION_LOG_S[SESSION_NUMBER].md:
  - Resumed at: [current timestamp]
  - Resumed from: [RESUME_TASK_ID]
  - Blocking issue resolution: [BLOCKING_ISSUE_RESOLUTION]

Command execution — critical: Do NOT chain commands using &&. Run each command
as a separate, sequential step.

BLOCKED TASK RESOLUTION
Re-run task [RESUME_TASK_ID] from scratch using the task CC prompt from
EXECUTION_PLAN.md. The engineer has resolved the blocking issue.

1. Execute the task CC prompt from EXECUTION_PLAN.md.
2. Run the verification command and evaluate all test cases.
3. If verification passes:
   - Update the Verification Record result for [RESUME_TASK_ID]
   - Record PASS verdict — confirm all checkboxes
   - Update session log: Status = Completed, record commit hash
   - Commit using the PBVI format:
     [SESSION_NUMBER].[TASK_NUMBER] — [Task Name]: [one-line summary]
   - Proceed immediately to RESUME EXECUTION below
4. If verification fails again:
   - Update session log: Status = BLOCKED (second attempt)
   - Write full verification output verbatim into the Verification Record
   - Write a one-line failure classification: ENVIRONMENTAL | SCOPE GAP | UNKNOWN
   - Output a SESSION BLOCKED summary (same format as the original failure)
   - Stop. Do not proceed further.

RESUME EXECUTION
After [RESUME_TASK_ID] is resolved and committed, execute all remaining tasks
in Session [SESSION_NUMBER] sequentially. All TASK-LEVEL VERIFICATION, FAILURE
HANDLING, GIT HYGIENE, and SCOPE AND INVARIANT RULES from the Session Execution
Prompt apply unchanged.
```

---

Session close — PR description: after all tasks committed and session log complete,
issue this to CC or CD ad hoc:

```
Draft a PR description for [branch] → main based on the session log and
verification record for Session [SESSION_NUMBER].
```

No named prompt required.

---

## Quick Reference

**Prediction rule:** Write predictions → run commands → record results. Never in any other order.

**Template rule:** Blank = cognitive work for the engineer. Pre-populated = factual copy from the plan.

**Git rule:** One branch per session. One commit per task. PR to main only after integration check.

**Invariant rule:** If a task prompt conflicts with an invariant, the invariant wins. Flag the conflict; never resolve it silently.

**Scope rule:** If something is not in the task prompt, do the minimum and flag the gap. Never fill gaps with judgment.

**Loop rule:** The loop is triggered by two things — a build failure, or a later phase exposing a gap in an earlier one. Both are valid triggers. Both require returning to the earlier phase. Forward progress built on an unresolved gap is not progress.

**Rule 3 rule:** Unregistered files are untrusted. CC flags them and reports to the engineer before proceeding. Engineer decides: register or remove.

**Failure rule (Autonomous mode):** Any verification failure stops the session immediately. No retry. No fix attempt. Record BLOCKED, output SESSION BLOCKED summary, wait for engineer.

**Resume rule:** After a BLOCKED stop, use the Autonomous Mode Resume prompt — not the full session prompt. Engineer supplies SESSION_NUMBER, RESUME_TASK_ID, and BLOCKING_ISSUE_RESOLUTION explicitly.

**Scope violation rule (Autonomous mode):** Any file boundary violation or pre-commit declaration failure stops the session immediately. No commit. No fix attempt. Record SCOPE VIOLATION, output SCOPE VIOLATION summary, wait for engineer disposition (ACCEPT or REVERT). Scope violations are signal — not noise to auto-resolve.

**Challenge rule (Autonomous mode):** After each task's verification passes and scope checks pass, the independent challenge agent runs against evidence only — no build session context. A CLEAN verdict proceeds to commit. A FINDINGS verdict stops the session. Engineer dispositions each finding: ACCEPT with rationale (no test required) or TEST with a test case (run immediately, must pass before session continues). Challenge findings are signal about coverage gaps — not automatic defects.

**Complexity rule:** A function, method, or handler is structurally compliant if it has a single stateable purpose and its conditional logic can be described in one sentence. Conditional nesting exceeding two levels is a structural violation. Flag it; never resolve it silently.

**BCE rule:** Phase 8 is not complete until Part 2 is done. Greenfield: all seven BCE artifacts committed (INTAKE_SUMMARY.md + five living + ANNOTATION_CHECKLIST.md), P1 items signed off, CD project files updated (Part 2A). Enhancement: ENH-NNN_BCE_IMPACT.md produced, gap detection CLEAN, engineer signed off (Part 2B). In a sprint context, ENH-NNN_BCE_IMPACT.md is the only BCE artifact produced per-enhancement close-out — updating discovery/ artifacts for a single enhancement mid-sprint is a process violation. All discovery/ updates are deferred to sprint close-out via Sprint Lead BCE refresh. CD project files updated at sprint close-out.

**Brownfield onboarding rule:** A brownfield system with completed BCE artifacts cannot enter the sprint path until PBVI-009 onboarding is complete. Sprint Prompt 0 enforces the Claude.md precondition. ARCHITECTURE.md is interpretive — for facts, see BCE source-of-record artifacts. Five-GLOBAL invariant ceiling is hard — no override.

**Phase 6 entry rule:** Every build session begins with Pre-Build Validation — schema validation against ID_REGISTRY.md plus CC interpretation confirmation. HALT or -WRONG returns the engineer to planning. No code is written until the engineer confirms CC's interpretation.

**Conversation Quality Review rule:** Every Phase 1–5 gate close in CD emits a Conversation Quality Review block — A/B/C/D grade plus Ownership and Dialogue observations plus next-time tips. Coaching, not gating; does not modify the gate verdict. Does not run in Phase 6–8.

**UI surface rule (PBVI-011):** UI_SURFACE.md is the functional contract for all screens. CC builds to the spec — it does not infer screen behaviour from component names or route conventions. If a screen's spec is incomplete, stop and return to Phase 1 UI Discovery before building that screen.

**UI test rule (PBVI-011):** Every task with a UI test spec (EXECUTION_PLAN.md item 7) must produce Playwright test assertions as part of task completion. Tests are committed in the same commit as the implementation. A task with a UI test spec is not complete until its tests are written and passing (or explicitly marked todo() with a reason referencing a future task).

**UI harness rule (PBVI-011):** UI_HARNESS.sh runs at Phase 8 completion and on-demand only. It does not run at session end — Playwright requires browser runtime. A passing UI harness is a Phase 8 completion requirement for UI projects.

**Seed rule (PBVI-011):** If data baseline = Seeded, the seed script task in Session 1 is not optional and is not deferred. Development, UI testing, and demo readiness all depend on seed data existing. A UI project with baseline = Seeded is not ready for Phase 6 Session 2 until the seed script passes verification.

---

## Conversation Quality Review

Fires automatically at the close of each Phase 1–5 gate. Cannot be skipped or deferred.
Applies to CD sessions only. Does not apply to Phase 6–8 build and integration sessions in CC.

**Purpose:** Give the engineer a graded assessment of their conversation quality for the
phase just completed — not the quality of the artifacts, but the quality of the dialogue
that produced them. Output is coaching, not judgment.

### Rubric

Claude assesses the conversation against two dimensions:

**Dimension 1 — Ownership**
Did the engineer demonstrate genuine understanding of the problem domain?
Observable signals:
- Engineer provided context, corrections, or domain knowledge that was not in the brief
- Engineer authored drafts first (invariants, decisions, architecture rationale)
  before asking for challenge
- Engineer could answer Claude's clarifying questions with concrete, domain-grounded
  answers
- Engineer made explicit decisions and stated reasons — not "what do you think is better?"
- At the gate, the engineer demonstrated they own the output — not just approved it

**Dimension 2 — Dialogue**
Was there a genuine two-way exchange, or did the engineer primarily receive?
Observable signals:
- Engineer pushed back on at least one Claude output with reasoning
- Engineer corrected a misinterpretation or added nuance Claude had missed
- When Claude flagged a gap or uncertainty, the engineer engaged with it — not accepted
  it or dismissed it
- Engineer asked follow-up questions that went deeper, not just confirmatory
- Engineer contributed signal that changed the direction of the conversation at least
  once

**Phase 1 weighting:** Dimension 2 (Dialogue) is weighted more heavily in Phase 1 than
in any other phase. Phase 1 is the most generative phase — its outputs depend most on
the engineer bringing domain knowledge Claude cannot infer. Passive reception in Phase 1
is the most significant early signal of output risk.

### Grade Definitions

| Grade | What it means |
|---|---|
| A | Strong ownership and genuine dialogue throughout. Engineer contributed domain signal, pushed back with reasoning, and demonstrated command of the output at the gate. |
| B | Adequate ownership and some dialogue. Engineer engaged on most points but defaulted to acceptance on some. Minor gaps in demonstrated ownership. |
| C | Thin ownership or thin dialogue. Engineer primarily received — accepted Claude outputs without substantive engagement, or delegated decisions that required their judgment. Output quality may be at risk. |
| D | Passive receipt. Engineer did not demonstrate ownership of the problem or outputs. Minimal pushback, minimal domain contribution, minimal engagement with flagged gaps. Proceed with caution — plan quality cannot be assumed. |

### Output Format

At the close of each Phase 1–5 gate, Claude outputs the following block before
confirming the gate result:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONVERSATION QUALITY REVIEW — PHASE [N]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Grade: [A / B / C / D]

Ownership: [2-3 sentences — specific observations from this conversation.
            What did the engineer demonstrate? What was thin?]

Dialogue:  [2-3 sentences — specific observations from this conversation.
            Was there genuine exchange? Where did it break down?]

Next time: [1-2 concrete, actionable tips for this engineer based on what
            was observed — not generic advice. Phase-specific where possible.]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The gate result (PASS / CONDITIONAL / RETURN TO EARLIER PHASE) follows immediately
after the quality review block — it is not delayed or withheld.

### Behaviour Rules

**Framing rule:** Observations must be drawn from this specific conversation.
Generic observations ("you could ask more questions next time") are not permitted.
If the conversation was short and signal is limited, say so explicitly — do not
fabricate observations.

**Authorship rule:** The quality review assesses the conversation. It does not
assess the artifacts, reassess the gate decision, or tell the engineer what their
artifacts should contain. These are separate concerns.

**Independence rule:** The CQR grade does not modify the gate verdict. A D grade
does not downgrade a PASS. The engineer is responsible for considering whether a
low CQR grade should affect their own confidence in the planning artifact, but the
gate logic does not consume the CQR grade as input.

**Limited signal rule:** If the conversation history available to Claude is short
or fragmented (for instance, the engineer began a new CD session mid-phase and
earlier exchanges are not in context), Claude says so explicitly in the Ownership
or Dialogue block — does not fabricate observations to fill the format.

---

## Where to Find Everything Else

| Content | Load |
|---|---|
| Enhancement framework, sprint lifecycle, sprint prompts, Phase 8 Part 2B | pbvi_sprint.md |
| Artifact templates (Session Log, Verification Record, SCOPE.md, Brief, Sprint artifacts) | pbvi_templates.md |
| BCE extraction (BCE-C), adapter pipeline, gap detection prompt, BCE impact template | bce_core.md |
| BCE-S signal extraction — adapters, Stage 1/2/3, SIGNAL_GAPS.md (Tier 3) | bce_signal.md |
| Always-on behavioural rules | dg_forge_org_skill (org setting) |

---

## Version Migration

Prompts for migrating projects initialised under earlier methodology versions.
Consult `BREAKING_CHANGES.md` in the DG-Forge repo to determine which migrations apply.

**Tool:** CD (read/update artifacts) then CC (commit changes)
**When to use:** When the version compatibility warning fires at a phase gate and you need to bring project artifacts up to the current skill version.

---

### Migrate to PBVI v3.0 — Invariant Scope Classification

**Applies to:** Projects with INVARIANTS.md produced before PBVI v3.0 — no Scope field (GLOBAL / TASK-SCOPED) on any invariant. Required before Phase 5 Claude.md generation will produce a correct Section 2.

**Trigger phrases:**
- "Migrate INVARIANTS.md to v3.0"
- "Add scope classification to invariants"

**Step 1 — Classify each invariant as GLOBAL or TASK-SCOPED (CD):**
```
Read INVARIANTS.md and EXECUTION_PLAN.md below. Classify each invariant as
GLOBAL or TASK-SCOPED using the following rule.

GLOBAL: must be held at every task in the system without exception — there is
no task that could plausibly execute without this invariant being relevant.
Goes into Claude.md Section 2. Maximum five.

TASK-SCOPED: applies only when specific components, features, or data
boundaries are touched. If any task in the plan could plausibly execute
without this invariant being relevant, it is TASK-SCOPED. Does not go into
Claude.md. Embedded inline in the CC prompt of each applicable task in
EXECUTION_PLAN.md.

For each invariant:
1. Propose GLOBAL or TASK-SCOPED
2. If TASK-SCOPED: list which tasks in EXECUTION_PLAN.md are affected and
   should carry this invariant inline in their CC prompt

Flag if more than five invariants would be classified GLOBAL — the engineer
must reduce to five maximum before proceeding.

INVARIANTS.md: [PASTE]
EXECUTION_PLAN.md: [PASTE]
```

Review CD's proposed classifications. Override any you disagree with and confirm
no more than five are GLOBAL before accepting.

**Step 2 — Update INVARIANTS.md and EXECUTION_PLAN.md (CC):**
```
Make the following changes based on the agreed scope classifications below.

1. Add a Scope field to every invariant in docs/INVARIANTS.md:
   Scope: GLOBAL
   or
   Scope: TASK-SCOPED

2. For each TASK-SCOPED invariant: embed the full invariant statement inline
   in the CC prompt of each applicable task in docs/EXECUTION_PLAN.md.
   Inline format:
   INVARIANT [INV-XX]: [full invariant statement]

3. Do not change any invariant statement, category, enforcement points, or
   Why This Matters field. Scope field and task-prompt embedding only.

Agreed classifications: [PASTE FROM STEP 1 OUTPUT]
```

**Step 3 — Update Claude.md (CC — only if Phase 5 has already run):**

If Claude.md exists, update Section 2 (Hard Invariants) to contain only GLOBAL
invariants. Remove any now classified TASK-SCOPED. Produce a new versioned
Claude.md following the immutability amendment process — new version number,
changelog entry, update PROJECT_MANIFEST.md.

**Step 4 — Commit:**
```
git add docs/INVARIANTS.md docs/EXECUTION_PLAN.md
git commit -m "chore: migrate [project-name] INVARIANTS.md to PBVI v3.0 scope split"
```

---

### Migrate to PBVI v4.1/v4.4 — Task Regression and Harness Classification (CQ-002)

**Applies to:** Projects with EXECUTION_PLAN.md produced before PBVI v4.1 — tasks have no regression classification field. Required before Phase 8 regression suite assembly produces a non-empty suite. Run the same prompt to adopt HARNESS-CANDIDATE classification introduced in PBVI v4.4.

**Trigger phrases:**
- "Migrate EXECUTION_PLAN.md to v4.1"
- "Add regression classification to tasks"

**Step 1 — Classify each task (CD):**
```
Read EXECUTION_PLAN.md and INVARIANTS.md below. Classify every task with a
regression classification using the three-value hierarchy.

HARNESS-CANDIDATE: verification command meets all four criteria —
(1) stateless — no session-specific setup required,
(2) portable — runnable from repo root without build context,
(3) executable against a running system,
(4) directly tied to a named invariant in INVARIANTS.md.
Assembled into both REGRESSION_SUITE.sh and HARNESS.sh at Phase 8.

REGRESSION-RELEVANT: verification command is portable (criteria 1 and 2
above) but does not meet all HARNESS-CANDIDATE criteria — no named invariant
tie, or requires a running system, or covers integration not invariant state.
Assembled into REGRESSION_SUITE.sh only.

NOT-REGRESSION-RELEVANT: verification command is not portable or produces
no independently verifiable artifact. One-line rationale required.

For each task:
- Propose the classification
- For REGRESSION-RELEVANT and HARNESS-CANDIDATE: confirm the verification
  command is stated and portable; flag any that need rewriting for portability
- For HARNESS-CANDIDATE: name the specific invariant (INV-XX) the command tests

EXECUTION_PLAN.md: [PASTE]
INVARIANTS.md: [PASTE]
```

Review classifications. Override where you disagree. Confirm all REGRESSION-RELEVANT
and HARNESS-CANDIDATE verification commands are portable before accepting.

**Step 2 — Update EXECUTION_PLAN.md (CC):**
```
Add regression classification as field 6 to every task in docs/EXECUTION_PLAN.md
based on the agreed classifications below. Update any verification commands flagged
as non-portable — rewrite to be runnable from repo root without session state.
Do not change any task description, CC prompt, test cases, or other fields.

Agreed classifications: [PASTE FROM STEP 1 OUTPUT]
```

**Step 3 — Assemble HARNESS.sh (CC — if any HARNESS-CANDIDATE tasks identified):**

Use trigger phrase "Assemble harness" to produce `verification/HARNESS.sh` from
all HARNESS-CANDIDATE tasks. If no HARNESS-CANDIDATE tasks exist after Step 2,
skip this step — the harness scaffold is produced automatically at Phase 8.

**Step 4 — Commit:**
```
git add docs/EXECUTION_PLAN.md
git commit -m "chore: migrate [project-name] EXECUTION_PLAN.md to PBVI v4.1 regression classification"
```
If harness was assembled: `git add verification/HARNESS.sh` before committing.

---

### Migrate to PBVI v4.3 — PHASE4_GATE_RECORD.md (PBVI-006)

**Applies to:** Projects with `PHASE4_RISK_DECISIONS.md` at repo root, produced before PBVI v4.3. Required before BCE Stage 1 can read accepted-risk entries from the correct path.

**Trigger phrases:**
- "Migrate PHASE4_RISK_DECISIONS.md to v4.3"
- "Migrate design gate record to v4.3"

**Step 1 — Rename, expand, and relocate (CC):**
```
Perform the PBVI v4.3 design gate record migration:

1. Copy content of PHASE4_RISK_DECISIONS.md — this becomes Section D of the
   new artifact.

2. Create docs/PHASE4_GATE_RECORD.md using Template 8 from pbvi_templates.md.
   Populate as follows:
   - Section A (Evaluation Criteria): if original Phase 4 session output is
     accessible, extract criteria. Otherwise enter: "BACKFILLED — original
     Phase 4 session not preserved; criteria not recoverable."
   - Section B (Requirements Traceability): same approach.
   - Section C (Adversarial Stress Test Findings): same approach.
   - Section D (Risk Register with Dispositions): copy from
     PHASE4_RISK_DECISIONS.md verbatim.
   - Engineer Sign-Off: copy sign-off from original file.

3. Update PROJECT_MANIFEST.md Core Documents table:
   - Add row: docs/PHASE4_GATE_RECORD.md | PRESENT | Phase 4 | Engineer |
     Design Gate record — evaluation criteria, requirements traceability,
     adversarial stress test findings, risk register with dispositions
   - Remove any existing PHASE4_RISK_DECISIONS.md row.

4. Delete PHASE4_RISK_DECISIONS.md from repo root.

Original PHASE4_RISK_DECISIONS.md content: [PASTE]
```

**Step 2 — Commit:**
```
git add docs/PHASE4_GATE_RECORD.md PROJECT_MANIFEST.md
git rm PHASE4_RISK_DECISIONS.md
git commit -m "chore: migrate [project-name] design gate record to PBVI v4.3 (PHASE4_GATE_RECORD.md)"
```

---

### Migrate to PBVI v4.5 — Failure Mode Fields (PBVI-008)

**Applies to:** Projects with INVARIANTS.md produced before PBVI v4.5 — missing Category, Authorship, and Failure Mode fields. Required before Phase 4 Step 2b (Invariant Failure Mode Review) can complete.

**Trigger phrases:**
- "Migrate INVARIANTS.md to v4.5"
- "Add failure mode fields to invariants"

**Step 1 — Add Failure Mode fields to INVARIANTS.md (CD):**
```
Read INVARIANTS.md below. For each invariant, add the following fields without
changing any existing invariant statements:

- Category: Structural | Data | Domain
  Structural = derived from architecture decisions (data flow, component boundaries,
  state mutation rules). Data = derived from schema/entity relationships (cardinality,
  nullability, state machine constraints). Domain = business rules and operational
  constraints not visible in architecture or schema.

- Authorship: Engineer-authored
  (All invariants in pre-v4.5 projects are engineer-authored — mark all as such.)

- Failure Mode:
    Violation: [observable state when the invariant is broken]
    Detection: [where and when it becomes visible — DB constraint at write time /
    application layer / verification test / production report / user report]
    Blast radius: [downstream consequence — data corruption, incorrect business
    decision, silent wrong answer, security exposure, financial loss]

Produce Failure Mode entries for every invariant. Engineer reviews and corrects
before accepting. Do not modify any INV-XX statement, scope, enforcement points,
or any other existing field.

INVARIANTS.md: [PASTE]
```

After CD produces the updated set: review every Failure Mode entry. Correct or
augment before accepting — this review IS the Phase 4 Step 2b for the existing invariants.

**Step 2 — Add INVARIANT_AUTHORSHIP_MODE to PROJECT_MANIFEST.md (CC):**
```
Add the following field to PROJECT_MANIFEST.md immediately after the
METHODOLOGY_VERSION line:

**INVARIANT_AUTHORSHIP_MODE:** GOVERNED — pre-v4.5 project; all invariants
engineer-authored under original authorship model.

Then update METHODOLOGY_VERSION to reflect the current skill version.
```

**Step 3 — Add Section E to PHASE4_GATE_RECORD.md (CC, if Phase 4 is complete):**

If PHASE4_GATE_RECORD.md exists and Phase 4 has already passed, add Section E
using Template 8 from pbvi_templates.md v3.9. Fill it using the Failure Mode
entries added in Step 1 — the migration review is the ownership test.

**Step 4 — Commit:**
```
git add docs/INVARIANTS.md PROJECT_MANIFEST.md docs/PHASE4_GATE_RECORD.md
git commit -m "chore: migrate [project-name] artifacts to PBVI v4.5 (PBVI-008)"
```
