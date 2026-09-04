STATUS: DRAFT — pre-formal. Backlog Entry and Sprint Assignment have not actually run yet
per the methodology (no `enhancements/REGISTRY.md`, no `SPRINT-001` directory, Sprint CC
Initiation hasn't been triggered). This is prep material to review before formalizing —
not the real `ENH-NNN_BRIEF.md`/`SPRINT-001_MANIFEST.md` files the methodology produces.

# SPRINT-001 (draft) — VIVE Statement Reconciliation

**Candidate enhancements:** 4, sized very differently. Bundled here at the engineer's
request for one combined review pass — actual `ENH-NNN` numbering/splitting happens at
real Backlog Entry, not necessarily 1:1 with the sections below.

---

## ENH-001 (draft) — UI clarity fixes + multiple PDF upload (merged 2026-09-02)

**Merge note:** originally drafted as two separate enhancements (UI clarity fixes, Tier 1
ready-now; multiple PDF upload, tier pending two open G4/G5 questions). Merged at the
engineer's explicit request, after flagging that this couples the ready UI fixes to
whatever tier the multi-PDF questions resolve to — if either open question below turns up
a real G4/G5 behavior change, **the whole combined enhancement**, including the UI items,
inherits that heavier sign-off tier, not just the upload-batching part.

**Type:** A — **Tier: 1, confirmed 2026-09-02** (G4/G5 questions answered directly against
source, no invariant-level change needed; see the IC-CANDIDATE-01 exposure note under Open
questions, which is a scope decision, not a tier-changing blocker).

**Problem:** Several small display/UX issues across Home, Upload, and Document Detail
make the current state of a document harder to read than it should be, and Upload
currently handles only one PDF at a time — batch upload would speed up real usage
(multiple vendor statements arriving together).

**Scope — Part A: UI clarity fixes**
1. Document Detail: show extraction and reconciliation summary together, e.g.
   "Extracted lines (273 total)" next to "Reconciliation complete — 140 matched, 133
   exceptions" — currently these apparently aren't shown adjacently.
2. Document Detail: remove the Provider and Confidence columns from the extracted-lines
   table.
3. Upload page: the "failed" state currently appears to trigger on *matching exceptions*,
   not just extraction failure — needs to only show for a genuine extraction failure.
   **Not yet verified against source** — `documentStatus.ts`'s badge computation is more
   layered than the symptom suggests (this is the same module where the earlier S7
   false-positive lived), so the actual root cause should be confirmed by reading the real
   badge logic before writing the fix, not assumed from the visible symptom.
4. Upload page: clicking a row should redirect to that document's extracted lines
   (Document Detail); uploaded-time display should show IST instead of whatever timezone
   it currently renders in.
5. Badge/label wording: "Done" → "Recon done"; "Success" → "Extraction success" (both
   currently read as ambiguous about which stage completed).

**Scope — Part B: Multiple PDF upload**
6. Allow selecting/uploading multiple PDFs in one action on the Upload screen.

**Open questions:**
- Item 3 needs a source read before it's a real acceptance criterion, not just a symptom
  description.
- Item 4's "redirect to extracted lines" — confirm this means Document Detail specifically
  (M-076/`DocumentDetailView.tsx`), not some other view.
- Timezone: is IST a fixed display choice, or should it eventually be user/locale-aware?
  Fixed-IST is a reasonable v1 scope given this is a single-region deployment; flagging so
  it's a conscious choice, not an assumption.
- ~~Item 6: does batch upload change how G4/G5 behave under concurrent registration?~~
  **ANSWERED 2026-09-02, verified directly against source (documents.ts:90-126,
  extraction.ts:36-38, UploadForm.tsx:37,157, extractionPipeline.ts).** G4 holds by
  design, not accident: `registerDocument()`'s catch block exists specifically to turn a
  check-then-insert race (explicitly reasoned about for multi-instance App Service in its
  own comment) into the same graceful `duplicate: true` response the DB's UNIQUE
  constraint already backstops — no code change needed. G5 is scoped per-`document_id`
  (`WHERE document_id = ? AND status != 'processing'`), so N different documents never
  contend; there is no table-level or global lock anywhere in the pipeline. Extraction
  timing: the existing single-file auto-trigger is already fire-and-forget
  (`UploadForm.tsx:157`), and `extractingIds` is already a `Set` — looping the same
  pattern over N new document IDs gives real parallelism with no changes required, since
  G5 imposes no cross-document ordering. **Tier estimate for this part confirmed: 1, no
  invariant-level code change needed for G4/G5 themselves.**
- **New risk surfaced by this analysis (add to scope, not a blocker):**
  `INVARIANT_CATALOGUE.md` IC-CANDIDATE-01 (extraction lock has no crash recovery — a
  document that hits `'processing'` and then throws is stuck forever, no `try/finally`
  unlike the matching lock's TTL-reclaim) is a **pre-existing** fragility, but batch
  upload multiplies exposure — N simultaneous live Claude/pdfplumber calls instead of one
  manual click meaningfully raises the odds that at least one throws and permanently
  strands its document. Worth an explicit decision: ship item 6 accepting the multiplied
  exposure, or fix IC-CANDIDATE-01's crash-recovery gap as part of this same enhancement
  (touches M-015/`extraction.ts`, M-046). Either is defensible — but it should be a
  conscious call, not discovered after the fact.

**Affected modules (from `discovery/MODULE_CONTRACTS.md`):** M-012 (documentStatus.ts,
badge logic — items 3, 5), M-013/M-076 (Document Detail, items 1, 2), M-070/M-068
(Upload/Home views, items 3, 4, 6), M-044 (upload route, item 6), M-011 (registration,
item 6), M-015 (extraction trigger, item 6).

---

## ENH-002 (draft) — Fix live Fabric connection

**Type:** B (touches invariant-adjacent connection/data-availability guarantees) —
**Tier estimate: 2 or 3**

**Problem — already evidenced, not speculative:** this is `RISK_REGISTER.md` R-008
(`FABRIC_SQL_ENDPOINT` is a bare hostname, not a valid connection string — confirmed
against the real `mssql`/`@tediousjs/connection-string` parser) plus R-004 (a failed
Fabric connect permanently poisons the connection-pool singleton, no auto-retry). These
compound: R-008 guarantees the very first connect attempt fails, which immediately
triggers R-004's permanent poisoning.

**Goal:** Reformat `FABRIC_SQL_ENDPOINT` as a real ADO connection string once an auth
scheme is chosen (SQL auth vs. Azure AD Managed Identity vs. AAD service principal
matching `FABRIC_LAKEHOUSE_SQL_ENDPOINT`'s existing pattern), and fix R-004's
non-retrying pool so a real transient failure doesn't permanently break the process.

**This is the most fully-scoped item on this list** — recommended action is already
written out in `RISK_REGISTER.md` R-008 itself.

**Affected modules:** M-003 (db.ts) — and transitively its 20+ callers.

---

## ENH-003 (draft) — Split front end and back end (not two Container Apps)

**Type:** unclear — **Tier: unclear, possibly not PBVI task-level work at all**

**Problem:** As given — "split front and backend, not two container apps." This reads as
a deployment/infrastructure architecture change, not application code, and it's currently
ambiguous which of two things is meant:
(a) currently deployed as two separate Container Apps and the ask is to consolidate/
    restructure that, or
(b) currently one thing and the ask is to split it, explicitly *not* via two separate
    Container Apps (i.e. some other split mechanism — e.g. one Container App with
    separate front/back processes, or a different Azure service entirely).

**Not scoped — needs clarification before this can become a real brief.** Also worth
deciding explicitly whether this is even `ENH-NNN`/PBVI-governed work (it may be an
infrastructure/ops decision that doesn't touch `src/` or invariants at all, in which case
the sprint/enhancement machinery may not be the right vehicle for it).

---

## ENH-004 (draft) — Vendor-specific invoice matching logic — NOT READY TO BRIEF YET

**Status:** investigation needed before this can be scoped as an enhancement at all.

**Why it's not ready:** unlike ENH-003, there's no existing evidence in
`discovery/MODULE_CONTRACTS.md` or `RISK_REGISTER.md` that `deterministicMatching.ts`
(M-026)'s generic invoice-ref-to-NetSuite-`tranid` comparison actually fails for any real
vendor. Writing acceptance criteria now would mean guessing at both the problem and the
fix.

**Recommended first step (not this enhancement — a short investigation):** run current
matching against real statements per known vendor and look at the match/exception split,
specifically the `not_posted` category rate per vendor (the signal for invoice-ref format
mismatch, as opposed to a genuine amount discrepancy). This mirrors exactly how the 9
extraction vendor-parsers got scoped in Session 8/9 — build only where evidence shows the
generic path fails, not speculatively.

**If the investigation finds real per-vendor mismatches**, ENH-005 gets written with real
acceptance criteria at that point (which vendors, what pattern, what fix). If it finds the
generic path already works, this item closes without ever becoming a build task.

---

## Readiness summary

| Item | Ready to formalize into a real ENH-NNN brief now? |
|---|---|
| ENH-001 (UI fixes + multi-PDF, merged) | **Mostly** — Part A item 3 still needs its source read; Part B's G4/G5 questions are now answered (Tier 1 confirmed), but carries a new open decision on IC-CANDIDATE-01 exposure |
| ENH-002 (Fabric connection) | **Yes** — already fully evidenced via R-008/R-004 |
| ENH-003 (front/back split) | No — needs clarification on what's actually being asked |
| ENH-004 (vendor matching) | No — needs an investigation pass first, not a brief |
