# S1 Execution Prompt — ENH-001 — UI Clarity Fixes

**Session:** S1
**Enhancement:** ENH-001
**Branch:** session/s1_ui_clarity_fixes
**Produced:** Phase 5 — 2026-09-03

---

## EXECUTION MODE

**Autonomous** — execute Tasks 1.1–1.4 sequentially without pausing between tasks. No
prediction statements. Stop only on a verification failure (BLOCKED).

Rationale: all four tasks are display-only changes with no invariant impact and no
interaction with the batch-upload design work — the lowest-risk half of this enhancement.

---

## AGENT IDENTITY

You are the build agent for ENH-001, Session S1. You have no memory of prior sessions.
All context you need is in this file and the planning artifacts listed below. Do not
infer context from session logs or other files not listed here.

---

## REPOSITORY CONTEXT

Session branch: `session/s1_ui_clarity_fixes`

Before any task work: confirm this branch exists and you are on it. If it does not exist,
stop immediately:

```
LAUNCH ERROR
------------
Branch session/s1_ui_clarity_fixes not found.
Create branch before launching this session.
```

Then read `PROJECT_MANIFEST.md` and locate `METHODOLOGY_VERSION`. Compare against the
loaded PBVI skill's frontmatter version. Match → proceed silently. Mismatch or absent →
output the standard methodology version warning, then continue (does not stop the
session).

---

## PLANNING ARTIFACTS — READ BEFORE TASK 1

Read in order:
1. `docs/Claude.md` — execution contract, governs everything (v1.4, unchanged this
   enhancement — v1.4 corrected stale pre-Phase-8 framing, not an ENH-001-relevant change)
2. `enhancements/SPRINT-001/ENH-001-ui-clarity-multi-pdf-upload/ENH-001_EXECUTION_PLAN.md`
   — Session 1 section, Tasks 1.1–1.4
3. `enhancements/SPRINT-001/ENH-001-ui-clarity-multi-pdf-upload/ENH-001_SPRINT_CONSTRAINTS.md`

If any listed file is missing, stop immediately:
```
LAUNCH ERROR
------------
[filename] not found.
Cannot begin session without complete planning artifacts.
```

---

## STEP 0 — PRE-BUILD VALIDATION (mandatory, no exceptions)

**Step A — Claude.md schema validation.** Read `Claude.md` and `ID_REGISTRY.md` (if
present). Run all schema checks per `pbvi_core.md` Phase 6 Pre-Build Validation Step A.
Output the SCHEMA VALIDATION RESULT table. HALT verdict → record in `SESSION_LOG.md`,
output `PRE-BUILD-PAUSED (HALT — schema invalid)`, stop session.

**Step B — Interpretation confirmation** (only if Step A is PASS or WARN). Read Task
1.1 (first task). Query `discovery/SYSTEM_GRAPH.json` for entry-point modules at depth 2.
Produce three statements: modules I will modify, invariants I will respect, blast radius
(in scope / out of scope / integration points / entities). Write both Step A and Step B
to `SESSION_LOG.md`'s Pre-Build Validation section before outputting.

**[HUMAN GATE — INTERPRETATION CONFIRMATION]**
Engineer responds CONFIRMED, or MODULES-WRONG / INVARIANTS-WRONG / BLAST-RADIUS-WRONG
(record rationale, output `PRE-BUILD-PAUSED (WRONG)`, stop session).

---

## WHAT HAS ALREADY BEEN BUILT

This is ENH-001's first session. No prior ENH-001 session state. Base application
(through Phase 8 sign-off, greenfield) is complete and live — this session extends it.

---

Begin by reading all PLANNING ARTIFACTS in order and confirming session state. Execute
Tasks 1.1 through 1.4 sequentially, in order, without pausing between tasks.
