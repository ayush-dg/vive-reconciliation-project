# REQUIREMENTS_BRIEF.md — VIVE Reconciliation

> **Draft status — CD-assisted, brownfield.** This project already has a full architecture,
> invariant set, and codebase (`docs/Claude.md` v2.9, `docs/ARCHITECTURE.md` v2.5,
> `docs/INVARIANTS.md`). This brief was drafted by reading those artifacts and the live code,
> not written independently and then checked against them. Per PBVI's Phase 1 Interrogate gate
> ("engineer owns the problem — can state it without AI assistance") and the GOVERNED
> brownfield authorship default, **this is a starting point for the engineer's review, not a
> substitute for it.** Correct, delete, or add anything below before treating it as received.
> Once signed off, `brief/` convention is "never modified after receipt" — file a superseding
> version rather than editing this one if requirements change later.
>
> **Why this exists now:** the original PBVI-009 onboarding (2026-07-24) was explicitly an
> *approximation* — `pbvi_brownfield.md` was unavailable at the time (see
> `PROJECT_MANIFEST.md`'s banner). It's available now. This brief is the input either to (a)
> a proper re-run of PBVI-009 Steps 2–5 against the real procedure, or (b) a fresh Phase 1
> Interrogate pass if the engineer wants to treat this as a genuine restart. That choice is
> the engineer's — not made here.

**Author:** [Engineer — pending]
**Date:** 2026-08-17
**Status:** [ ] Draft | [ ] AI Review Complete | [ ] Signed Off

---

## 1. Business Context

VIVE Collision is a multi-shop auto body repair company (~79 shops, Northeast US). Vendor
suppliers (parts, materials, services) send monthly PDF statements listing outstanding
invoices. Today, the AP team reconciles each vendor statement against VIVE's ERP records
by hand — a manual, hours-long, per-vendor cross-check, repeated every month, per vendor.

**The problem this system solves:** eliminate the manual cross-check by automatically
extracting line-item data from vendor PDFs, comparing it deterministically against ERP
records, and surfacing only the discrepancies that need a human decision.

**What this system explicitly does not do:** approve, reject, or execute any payment. It
identifies discrepancies; a human AP reviewer acts on them.

---

## 2. Who Uses This

- **AP team (primary users):** upload vendor statements, review flagged exceptions and
  low-confidence extractions, disposition each one (accept / dispute / write off / escalate).
- Single-tier user model today — no Admin/Reviewer role split exists or is currently in scope
  (`web/routers/users.py:4`; see §7 Out of Scope).

**Missing information (flag for Interrogate):** is a role split (e.g. reviewer vs. approver
vs. admin) a real future requirement, or is flat access a deliberate, durable decision for
this business? `docs/Claude.md` §3 currently lists it as explicitly out of scope without a
stated timeline.

---

## 3. What The System Must Do

1. **Extract** line-item invoice data from vendor PDF statements — AI-primary
   (Claude Sonnet 4.6), with a deterministic fallback (pdfplumber + OCR) when needed.
   Column mapping is universal across vendors — no per-vendor configuration.
2. **Compare** extracted invoices against ERP records (currently a mock ERP generator,
   pending live NetSuite access) using a fully deterministic matching engine — never AI.
3. **Classify** every line item as matched or as one of four exception types (MISSING,
   AMOUNT_MISMATCH, EXTRACTION_INCOMPLETE, DUPLICATE_RECORD), each carrying a numeric
   confidence score.
4. **Route** anything below a confidence threshold to human review rather than
   auto-passing it through.
5. **Present** exceptions and review-queue items to the AP team via a web dashboard,
   grouped by vendor, with aging and bulk-approve support for high-confidence matches.
6. **Record** who actioned which exception, how, and when — an audit trail, since this
   data carries real financial consequences.
7. **Ingest** statements two ways: manual upload, and an automated drop-zone (blob storage
   + webhook) for vendors who can deliver PDFs directly.

---

## 4. What The System Must Never Do (candidate non-negotiables)

These are drawn directly from `docs/INVARIANTS.md` / `docs/Claude.md` §2 — restated here in
business terms for Interrogate, not as a replacement for the formal invariant set:

- Never let a low-confidence extraction silently pass through as if it were verified data —
  it must be routed to a human instead.
- Never treat a summary or totals row (grand total, subtotal, balance-forward) as if it
  were a real invoice line.
- Never write a reconciliation record with a missing invoice number or missing amount.
- Never let the deterministic matching engine (Passes 1–2) consult an AI model, for any
  reason — matching decisions must be reproducible and explainable without an LLM in the loop.
  (A narrowly-scoped, non-auto-approving AI disambiguation step — Pass 3 — is permitted only
  on the residual left after Passes 1–2; see `docs/INVARIANTS.md` INV-02 for the full,
  five-part-constrained exception. No Pass 3 code exists yet.)
- Never process the same statement file twice concurrently.

**Flag for Interrogate:** all five are currently engineer-authored judgment calls (GOVERNED
mode), and at least two carry explicit caveats worth surfacing to a fresh Interrogate pass:
INV-01's 0.90 threshold was raised without production disposition data to validate it, and
INV-02's Pass 3 exception was decided by one engineer while the Sprint Lead was on leave,
still provisional pending her confirmation.

---

## 5. Current State (brownfield — what already exists vs. what's still a gap)

Read `docs/ARCHITECTURE.md` for full detail. Summary for Interrogate purposes:

**Built and working:** the full extraction → match → exception → review pipeline; the web
dashboard and all its routers; the 3-worker background job pool; the blob drop-zone intake
webhook (now authenticated); bulk-approve; exception aging/escalation.

**Partially built:** the storage-platform migration to Microsoft Fabric. Three of seven
"Recon" operational tables (`extraction_cache`, `document_intake_log`,
`validation_document_review_queue`) are cut over to a real SQL database in Fabric item.
The other four Recon tables (`jobs`, `exception_dispositions`, `users`, `ai_audit_log`) and
all of Bronze/Silver/Gold remain on Azure SQL/SQLite. The job queue the worker pool polls
is one of the *not-yet-migrated* tables — a real dependency for anyone assuming the
migration is closer to done than it is.

**Deliberately not built:** live NetSuite integration (mock ERP stands in until API access
is granted), per-vendor column mapping, AI inside the matching engine, role-based
permissions, email alerts, per-file fault isolation within a batch, and a document-level
aggregate confidence gate.

**Blocked, not by design:** Event Grid System Topic creation and App Service deployment are
both blocked on Azure RBAC / subscription quota the engineer doesn't currently hold —
reported to Ashrith, unresolved as of the last architecture update.

---

## 6. Definition of Success

If this system works correctly: every vendor statement's invoices are either matched with
high confidence and require no human attention, or are correctly routed to a human reviewer
— never silently misclassified either way. Success is measured by AP team time saved per
vendor per month and by the absence of missed or wrongly-auto-cleared discrepancies, not by
extraction volume alone.

**Missing information (flag for Interrogate):** there is no stated target number (e.g. "AP
time per vendor drops from X hours to Y") or accuracy threshold against real disposition
data — INV-01's threshold note above says explicitly that too few real dispositions exist
yet to validate the current confidence gate. This is a genuine open question, not an
oversight to paper over.

---

## 7. Explicitly Out of Scope (do not build without a new enhancement decision)

- Live NetSuite integration
- Per-vendor column mapping configuration
- Any AI involvement inside the deterministic matching engine itself
- Full role-based permission tiers (Admin/Reviewer split)
- Document-level aggregate confidence gate
- Email alerts (provider decision pending)
- Per-file fault isolation within an intake batch

---

## 8. Open Questions for Interrogate / Engineer Decision

1. Is this brief the input to a proper PBVI-009 re-run (finish onboarding correctly now that
   `pbvi_brownfield.md` is available), or a full Phase 1 restart? Determines whether
   `docs/ARCHITECTURE.md`/`docs/INVARIANTS.md` are re-derived from BCE artifacts or replaced
   outright.
2. Role-based permissions — durable decision or deferred requirement?
3. What does "success" look like numerically — AP hours saved, target confidence accuracy,
   or something else measurable once real disposition data exists?
4. Timeline/priority on completing the Fabric migration for the remaining four Recon tables
   and Bronze/Silver/Gold — is this urgent (production readiness) or can it continue to trail
   behind feature work?
5. INV-02's Pass 3 AI-disambiguation exception is provisional pending the Sprint Lead's
   return — does it need her sign-off before any Pass 3 code is written, or before this
   brief itself is signed off?
6. Timeline for live NetSuite access — the single biggest gap standing between this system
   and real production value, per `docs/ARCHITECTURE.md` §8.

---

## 9. Stakeholders

- **Engineer / building:** Ayush Kumar Sinha
- **Sprint Lead:** [on leave as of the last architecture update — confirm current status]
- **Azure/infra escalation contact:** Ashrith (RBAC, subscription quota)
- **Business owner / AP team:** [not yet named in existing artifacts — confirm]

---

## Engineer Sign-Off

[ ] I confirm this brief is accurate to my current understanding.
    Phase 1 (or the PBVI-009 re-run) may surface new information not reflected here.

**Signed:** ______________________
**Date:** ______________________
