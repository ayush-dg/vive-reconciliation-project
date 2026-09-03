# S2 Execution Prompt — ENH-001 — Multiple PDF Batch Upload

**Session:** S2
**Enhancement:** ENH-001
**Branch:** session/s2_batch_upload
**Produced:** Phase 5 — 2026-09-03

---

## EXECUTION MODE

**Manual** — pause after each task (2.1–2.4) for the engineer's prediction statement,
challenge-finding dispositions, and commit confirmation before proceeding to the next
task. No skipping ahead.

Rationale: this session carries the Design Gate rework — Task 2.1's crash-recovery fix
in particular has a subtle failure mode (`hasAlreadySucceeded` silently no-op'ing on a
naive retry) that was only caught by close source reading, not by the original task
description. Given that history, this session is not treated as routine — each task gets
a checkpoint.

---

## AGENT IDENTITY

You are the build agent for ENH-001, Session S2. You have no memory of prior sessions,
including S1. All context you need is in this file and the planning artifacts listed
below. Do not infer context from session logs or other files not listed here.

---

## REPOSITORY CONTEXT

Session branch: `session/s2_batch_upload`

Before any task work: confirm this branch exists and you are on it, and that
`session/s1_ui_clarity_fixes` has already been merged to main (S1 → S2 is a sequential
dependency within this enhancement — S2's per-row UI work builds on S1's screens). If the
branch does not exist, stop immediately:

```
LAUNCH ERROR
------------
Branch session/s2_batch_upload not found.
Create branch before launching this session.
```

Then read `PROJECT_MANIFEST.md` and locate `METHODOLOGY_VERSION`. Compare against the
loaded PBVI skill's frontmatter version. Match → proceed silently. Mismatch or absent →
output the standard methodology version warning, then continue.

---

## PLANNING ARTIFACTS — READ BEFORE TASK 1

Read in order:
1. `docs/Claude.md` — execution contract, governs everything (v1.4, unchanged this
   enhancement — v1.4 corrected stale pre-Phase-8 framing, not an ENH-001-relevant change)
2. `enhancements/SPRINT-001/ENH-001-ui-clarity-multi-pdf-upload/ENH-001_EXECUTION_PLAN.md`
   — Session 2 section, Tasks 2.1–2.4 (Task 2.1 reflects the Design Gate rewrite — read
   its Design note in full before starting, not just the CC prompt)
3. `enhancements/SPRINT-001/ENH-001-ui-clarity-multi-pdf-upload/ENH-001_SPRINT_CONSTRAINTS.md`
4. `enhancements/SPRINT-001/ENH-001-ui-clarity-multi-pdf-upload/ENH-001_PHASE4_GATE_RECORD.md`
   — Section C Findings 1–3 and Section D dispositions. Task 2.1, 2.2, and 2.3's CC
   prompts already incorporate these; this file is background for *why*, read if the
   CC prompt's reasoning needs more context mid-task.

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

**Step B — Interpretation confirmation** (only if Step A is PASS or WARN). Read Task 2.1
(first task). Query `discovery/SYSTEM_GRAPH.json` for entry-point modules at depth 2 —
this should surface M-015 and M-022 both, given Task 2.1 now touches both. Produce three
statements: modules I will modify, invariants I will respect, blast radius. Write both
Step A and Step B to `SESSION_LOG.md`'s Pre-Build Validation section before outputting.

**[HUMAN GATE — INTERPRETATION CONFIRMATION]**
Engineer responds CONFIRMED, or MODULES-WRONG / INVARIANTS-WRONG / BLAST-RADIUS-WRONG
(record rationale, output `PRE-BUILD-PAUSED (WRONG)`, stop session). If the interpretation
doesn't name **both** M-015 and M-022 for Task 2.1, that's MODULES-WRONG — a strong signal
the agent hasn't actually read Task 2.1's Design note.

---

## WHAT HAS ALREADY BEEN BUILT

S1 delivered the four UI clarity fixes (status label renames, combined Document Detail
summary, Upload click-through, IST timestamps) — merged to main, verified, no known
issues. This session builds on that baseline; no batch-upload code exists yet.

---

Begin by reading all PLANNING ARTIFACTS in order and confirming session state. Present
Task 2.1 and wait for the engineer's prediction statement before running any verification
command.
