# ENH-001_BRIEF.md

**Enhancement ID:** ENH-001
**Title:** UI clarity fixes (Home/Upload/Document Detail) + multiple PDF upload
**Author:** Vaishali
**Date:** 2026-09-02
**Status:** [x] Draft | [ ] AI Review Complete | [ ] Signed Off

---

## Enhancement Intent

Two related pieces of work bundled together at the engineer's request for one combined
review pass. First: a set of small display/wording fixes across Home, Upload, and
Document Detail that make a document's current state easier to read at a glance — showing
the extraction/reconciliation summary together, dropping two columns from the
extracted-lines table that aren't useful day-to-day, fixing a status badge that currently
reads as "failed" for cases that are actually reconciliation exceptions rather than a real
extraction failure, adding a click-through from Upload to a document's extracted lines,
switching the displayed upload time to IST, and renaming two ambiguous status labels so
it's clear which stage ("extraction" vs "reconciliation") actually completed. Second:
allowing multiple PDFs to be selected and uploaded in one action on the Upload screen,
instead of one at a time. These were merged into a single enhancement by engineer
decision, after being flagged that doing so couples the (already fully evidenced, ready)
UI fixes to whatever sign-off tier the multi-PDF item ends up needing — investigation
since then (see Known Constraints) found the multi-PDF item needs no invariant-level
changes, so this remains Tier 1 as originally hoped.

---

## Known Touch Points

| Touch Point | BCE Artifact | Entry |
|---|---|---|
| Document status badge computation | MODULE_CONTRACTS.md | M-012 (documentStatus.ts) |
| Document Detail data assembly | MODULE_CONTRACTS.md | M-013 (documentDetail.ts) |
| Document Detail screen | MODULE_CONTRACTS.md | M-076 (DocumentDetailView.tsx) |
| Upload screen | MODULE_CONTRACTS.md | M-070 (UploadForm.tsx) |
| Home screen | MODULE_CONTRACTS.md | M-068 (HomeView.tsx) |
| Document registration (G4 dedup) | MODULE_CONTRACTS.md | M-011 (documents.ts) |
| Extraction trigger (G5 lock) | MODULE_CONTRACTS.md | M-015 (extraction.ts) |
| Upload API route | MODULE_CONTRACTS.md | M-044 (api/documents/route.ts) |
| Document entity / upload_timestamp, status fields | TOPOLOGY.md / DOMAIN_MODEL.json | A01 (Document registration crossing) / E-001 (Document entity) |

---

## Known Constraints

| Constraint | Type | Notes |
|---|---|---|
| Must not change G4 (content-hash dedup) or G5 (processing-ownership lock) semantics | MANDATORY | Verified compatible with multi-PDF as currently designed — `registerDocument()`'s existing race-tolerant catch block and `extraction.ts`'s per-`document_id` lock already handle concurrent registration/extraction correctly with no code change (verified directly against source, 2026-09-02: `documents.ts:90-126`, `extraction.ts:36-38`). This constraint exists to keep it that way, not because a change is anticipated. |
| Must not require a database schema change | MANDATORY | Keeps this Tier 1 (Type A). If any item below is found to need a schema change once in Phase 1, that item should be split into its own Type B enhancement rather than pulling this one up a tier. |
| IC-CANDIDATE-01 (extraction lock has no crash-recovery path) — batch upload multiplies exposure | OPTIONAL | Pre-existing fragility, not introduced by this enhancement, but N simultaneous extraction calls instead of one manual click raises the odds that at least one throws and permanently strands its document. Open decision, not yet made: fix the crash-recovery gap as part of this enhancement's scope, or ship accepting the multiplied exposure. Revisit in Phase 1 — do not default silently to either choice. |
| Root cause of the failed/exceptions badge issue (item 3) not yet confirmed against source | OPTIONAL | Symptom described by the engineer; `documentStatus.ts`'s actual badge logic (the same module the earlier S7 false-positive lived in) needs to be read before this is a real acceptance criterion, not assumed from the visible symptom. |
| Upload-time display fixed to IST (not user/locale-configurable) | OPTIONAL | Reasonable v1 scope for a single-region deployment; noted so it's a conscious choice, revisitable later, not an oversight. |
| No defined maximum batch size for multiple PDF upload | OPTIONAL | Not yet decided — engineer to set a limit (or explicitly decide "no limit") during Phase 1. |

---

## Out of Scope

- Fabric SQL connection fix (`RISK_REGISTER.md` R-008/R-004) — separate enhancement (ENH-002).
- Vendor-specific invoice matching logic — not yet ready to scope as an enhancement at all;
  needs its own investigation first (see `enhancements/` backlog notes).
- Front-end/back-end deployment architecture change — separate concern, possibly not
  PBVI-governed task-level work at all.
- Any change to G4 or G5 invariant semantics themselves (see Known Constraints — this
  enhancement relies on existing behavior, it does not modify it).
- General internationalization/timezone configurability beyond the fixed IST display
  choice above.
- Whether to fix IC-CANDIDATE-01's crash-recovery gap is explicitly **not** pre-decided
  here — see Known Constraints; it is deferred to a Phase 1 decision, not ruled in or out.

---

## Engineer Sign-Off
[x] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**Signed:** Vaishali
**Date:** 03-09-2026
