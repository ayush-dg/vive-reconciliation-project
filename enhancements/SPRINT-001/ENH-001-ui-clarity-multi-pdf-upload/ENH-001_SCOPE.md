# ENH-001_SCOPE.md — UI clarity fixes + multiple PDF upload
**Enhancement:** ENH-001
**Engineer:** Vaishali
**Type:** A
**Status:** SCOPED

## 1. Enhancement Summary
Two bundled pieces of work. First, small display/wording fixes to Home, Upload, and
Document Detail: combined extraction/reconciliation summary display, dropping two
unused columns from the extracted-lines table, a click-through from Upload to a
document's extracted lines, upload time displayed in IST, and renaming two ambiguous
status labels ('Done' → 'Recon done', 'Success' → 'Extraction success') so it's clear
which stage completed. Second, multiple PDFs selectable and uploaded in one action on
Upload, processed sequentially with visible per-file progress, a running success-only
toast counter, and a fix to extraction's crash-recovery gap (IC-CANDIDATE-01) that
batch upload would otherwise multiply exposure to.

## 2. Scope

**In scope:**
- Status label renames — 2-line edit in `HomeView.tsx`'s existing badge-label function
- Extraction/reconciliation summary display combination (Document Detail)
- Drop two unused columns from extracted-lines table (Document Detail)
- Click-through from Upload to a document's extracted lines
- Upload time display in IST
- Multi-PDF selection and sequential, throttled batch upload (Upload screen)
- Per-file progress state during batch upload
- Running success-only toast counter ("X/N uploaded"), N fixed at batch start
- Registration failure mid-batch: skip and continue, not fatal to the batch
- Crash-recovery fix for extraction lock (IC-CANDIDATE-01): distinguishable
  `SilverNormalizationFailure` error type in `extractionPipeline.ts` (M-022) plus an
  opt-in guard-bypass on retry, wired from `extraction.ts`'s (M-015) crash-recovery catch
  — narrowed at the Design Gate from an initial generic try/finally after discovering
  the naive version would silently no-op on retry (see `ENH-001_PHASE4_GATE_RECORD.md`
  Finding 1)
- Batch size cap: 15 files

**Out of scope:**
- Fabric SQL connection fix (R-008/R-004) — ENH-002
- Vendor-specific invoice matching logic — not yet scoped
- Front-end/back-end deployment architecture change
- Any change to G4 or G5 invariant semantics
- General internationalization/timezone configurability beyond fixed IST
- A dedicated job/worker queue for extraction — explicitly rejected, client-side
  sequencing only
- The status badge "failed vs. exception" issue — pre-existing, already fixed
  2026-08-31 in `HomeView.tsx`, not a real issue for this enhancement

## 3. BCE Impact Assessment
Planning declaration only — no `discovery/` updates here; deferred to sprint close-out
via Sprint Lead BCE refresh.

No structural BCE artifact impact expected. All touch points (M-011, M-012, M-013,
M-015, M-022, M-044, M-068, M-070, M-076, M-009) are existing modules with no new module
boundaries, no new integration points, and no schema change. M-022 (`extractionPipeline.ts`)
was added at the Design Gate — Task 2.1's crash-recovery fix (Finding 1) turned out to
require a small, exported change there (a distinguishable error type and an opt-in
guard-bypass parameter), not just a change in M-015. `RISK_REGISTER.md`
entries R-005 (IC-CANDIDATE-01) and R-007/IC-CANDIDATE-02 are both addressed by this
enhancement's decisions — R-005 gets an actual code fix; R-007 is confirmed unaffected
(existing default-entity behavior unchanged). Expect `ENH-001_BCE_IMPACT.md` at close-out
to record R-005's mitigation and both risks' AFFECTED/NOT AFFECTED status, but no
`discovery/` artifact structurally changes shape.

## 4. Invariants Touched

| INV-ID | Scope | Action | Notes |
|---|---|---|---|
| G4 | GLOBAL | TOUCHES | Content-hash dedup — relied on unchanged for batch registration, not modified |
| G5 | GLOBAL | TOUCHES / ENFORCES (extended) | Processing-ownership lock — existing per-`document_id` guard unchanged; crash-recovery fix adds a status-reset finally block around the existing lock's call site, not a new lock mechanism |
| S1 | TASK-SCOPED | TOUCHES | Upload never triggers matching — unaffected by batch upload, still true by construction |
| S4 | TASK-SCOPED | TOUCHES | legal_entity_id required on registration — unaffected, same fixed default used for every file in a batch |
| S7 | TASK-SCOPED | TOUCHES | Max 2 extraction attempts — unaffected, per-file retry logic unchanged by sequencing |

No new invariants — GLOBAL or TASK-SCOPED. The new batch-upload behavioral rules
(sequential-only extraction, corrupt-file-skip, counter semantics) were explicitly
decided to live as `EXECUTION_PLAN.md` task-level acceptance criteria, not as formal
invariants — narrow, enhancement-local behaviors, not cross-cutting system guarantees.

## 5. Claude.md Impact
**Version bump required:** NO
**Reason:** No new GLOBAL invariant, no scope boundary change (`/src/**` already covers
every file this enhancement touches), no new prohibited behaviour. Confirmed against
current Claude.md Section 3 (Scope Boundary) and Section 4 (Fixed Stack) before this
determination — nothing in the Fixed Stack changes either.

## 6. Sign-Off Tier

**Tier:** 2

Decision criteria: Type A, but multi-session given scope (UI fixes + batch upload +
crash-recovery fix + sequential-extraction logic + toast counter — realistically more
than one build session). No invariant enforcement point changes beyond G5's existing
enforcement being extended with a finally-block reset, which is a hardening of an
existing enforcement point, not a new one or a changed detection mechanism — noted here
for the record in case this pushes toward re-evaluation once `EXECUTION_PLAN.md` exists.

**Part 1 sign-off artifact:** `ENH-001_VERIFICATION_CHECKLIST.md` — changed invariants
only (in practice, likely just confirming G5's extended enforcement still holds under
the crash-recovery fix, plus S1/S4/S7 spot-checks against batch upload).

## 7. Phase 3 Gate — Tier Reconfirmation

**Trigger:** Before beginning Phase 3 (execution planning).

[x] The Sign-Off Tier declared in Section 6 remains appropriate given what Phases 1 and
    2 surfaced.

Unchanged as of this document's creation — Tier 2 stands. Reconfirm at the top of Phase
3 before producing `ENH-001_EXECUTION_PLAN.md`, since session count will be concrete by
then.

**Tier change record:** N/A — no change yet.

## 8. Engineer Sign-Off (Scoping Gate)
I confirm the scope, BCE impact, invariant assessment, and Sign-Off Tier above are
accurate to my current understanding before build begins.

**Signature:** Vaishali
**Date:** 03-09-2026