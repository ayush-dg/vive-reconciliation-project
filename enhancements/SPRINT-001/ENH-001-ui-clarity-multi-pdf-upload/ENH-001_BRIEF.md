# ENH-001_BRIEF.md

**Enhancement ID:** ENH-001
**Title:** UI clarity fixes (Home/Upload/Document Detail) + multiple PDF upload
**Author:** Vaishali
**Date:** 2026-09-02
**Status:** [] Draft | [x] AI Review Complete | [x] Signed Off

---

## Enhancement Intent

Two related pieces of work bundled together at the engineer's request for one combined
review pass. First: a set of small display/wording fixes across Home, Upload, and
Document Detail that make a document's current state easier to read at a glance — showing
the extraction/reconciliation summary together, dropping two columns from the
extracted-lines table that aren't useful day-to-day, adding a click-through from Upload to
a document's extracted lines, switching the displayed upload time to IST, and renaming two
ambiguous status labels so it's clear which stage ("extraction" vs "reconciliation")
actually completed — this last item (the renames) is the only real remaining work from
what was originally a two-part status-labeling fix; the other part, a status badge
suspected of misreading matching exceptions as "failed," turned out on investigation to be
pre-existing and already fixed 2026-08-31 in `HomeView.tsx`, and is out of scope here (see
Out of Scope). Second: allowing multiple PDFs to be selected and uploaded in one action on
the Upload screen, instead of one at a time. These were merged into a single enhancement by
engineer decision, after being flagged that doing so couples the (already fully evidenced,
ready) UI fixes to whatever sign-off tier the multi-PDF item ends up needing —
investigation since then (see Known Constraints) found the multi-PDF item needs no
invariant-level changes, so this remains Tier 1 as originally hoped.

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
| Toast counter `add()`/`dismiss()` calls | MODULE_CONTRACTS.md | M-009 (toastStore.ts) — the actual pub/sub store these calls live in; distinct from M-083 (ToastProvider.tsx), which only renders and exposes `useToast` |

---

## Known Constraints

| Constraint | Type | Notes |
|---|---|---|
| Must not change G4 (content-hash dedup) or G5 (processing-ownership lock) semantics | MANDATORY | Verified compatible with multi-PDF as currently designed — `registerDocument()`'s existing race-tolerant catch block and `extraction.ts`'s per-`document_id` lock already handle concurrent registration/extraction correctly with no code change (verified directly against source, 2026-09-02: `documents.ts:90-126`, `extraction.ts:36-38`). This constraint exists to keep it that way, not because a change is anticipated. |
| Must not require a database schema change | MANDATORY | Reviewed at the brief review gate (2026-09-03) as a possible Category 3 implicit-assumption flag — confirmed genuinely MANDATORY, not relabeled. This is a scope-routing rule, not a claim that no schema change is technically possible: it says what happens if Phase 1 finds one is needed — that item splits into its own Type B enhancement — rather than leaving room for this enhancement itself to absorb a schema change and quietly inherit Tier 3. Kept MANDATORY (not OPTIONAL) precisely because it isn't meant to be re-evaluated away in Phase 1; Phase 1's role here is to detect the trigger condition, not renegotiate the rule. |
| IC-CANDIDATE-01 (extraction lock has no crash-recovery path) — batch upload multiplies exposure | **MANDATORY** — resolved 2026-09-03 | **Decision: fix it, as part of this enhancement.** Approach confirmed: wrap `runExtractionPipeline(documentId)`'s call site (`extraction.ts:49`) in a try/finally that resets the document's status on a thrown failure instead of leaving it stuck at `'processing'` — no new column, no schema change, stays Tier 1. (Alternative considered and rejected: a TTL-timestamp column mirroring the matching lock's staleness-reclaim — would have required a schema change and likely bumped this to Tier 2.) |
| Extraction must run **sequentially, one file at a time, with visible per-file progress** — NOT parallel/unthrottled | **MANDATORY** — added 2026-09-03 | Explicit engineer requirement, not the default outcome of extending the existing pattern. The current single-file auto-trigger (`UploadForm.tsx:157`) is fire-and-forget with no sequencing at all — naively looping it over N files would fire all N extraction calls (including N live Claude API calls) at once, with no throttling. That is explicitly rejected. The client loop must await each file's registration+extraction before starting the next, updating that file's own progress state as it goes. |
| Legal-entity assignment under batch upload | **RESOLVED 2026-09-03 — no action needed** | Confirmed: every upload already gets the same fixed default entity today, single or batch — this is existing, already-accepted behavior, not something multi-upload changes. No special batch handling required, unless something is specified later. |
| Toast notification behavior under batch upload (one popup per file vs. one consolidated summary) | **RESOLVED 2026-09-03** | Running success-only counter toast: "X/N uploaded", updated by dismissing the previous toast and adding a new one on each file's completion (reuses existing `dismiss()`/`add()` in `toastStore.ts`, M-009 — no new primitive, `M-083` stays untouched, rendering only). UploadForm (M-070) tracks the current toast id across the batch loop. Failures are NOT rolled into this counter — shown per-row via existing per-file progress state instead, consistent with the sequential-extraction constraint above. **Counter semantics, tightened 2026-09-03:** `N` is the batch's total file count, fixed at batch start — never recalculated on failure. The numerator `X` increments only on success. A 10-file batch with 3 failures ends at "7/10," not "10/10" or "7/7." |
| Status label renames ('Done' → 'Recon done', 'Success' → 'Extraction success') | **RESOLVED — confirmed 2026-09-03** | Now the only real remaining work from what was originally a two-part status-labeling fix — the badge-fix half was removed (pre-existing, already fixed 2026-08-31 in `HomeView.tsx`; see Out of Scope). A 2-line string edit within the same function already covered by an existing declared touch point above — no new touch point needed beyond what's already declared. |
| A registration failure mid-batch is skipped, not fatal to the batch | **MANDATORY** — added 2026-09-03 | The loop continues to the next file. Consistent with per-file status and the success-only counter design. |
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
- ~~Whether to fix IC-CANDIDATE-01's crash-recovery gap~~ — **resolved 2026-09-03, in
  scope, not out of scope.** See Known Constraints for the confirmed fix approach
  (try/finally status reset, no schema change).
- A dedicated job/worker queue for extraction — explicitly rejected; see the sequential-
  extraction constraint above. This enhancement extends the existing single-request
  pattern with client-side sequencing, not new backend orchestration infrastructure.
- The status badge originally suspected of misreading matching exceptions as "failed" —
  investigated 2026-09-03 and found to be pre-existing, already fixed 2026-08-31 in
  `HomeView.tsx`. Not a real issue for this enhancement; removed from scope (see
  Enhancement Intent).

---

## Engineer Sign-Off
[x] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**Signed:** Vaishali
**Date:** 03-09-2026
