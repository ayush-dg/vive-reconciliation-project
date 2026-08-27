# REQUIREMENTS_BRIEF.md — VIVE Statement Reconciliation (Ground-Up Build)


---

## 1. Business Context

VIVE Collision operates ~79 auto body repair shops in the Northeast US, with a stated growth
target of 150 shops. Vendor suppliers send monthly statements listing outstanding invoices;
VIVE's AP team must reconcile each statement against VIVE's own records before anything gets
paid or disputed.

**The staffing math that makes this a build, not a nice-to-have:** VIVE currently staffs
reconciliation at roughly one AP employee per seven shops (~11.3 FTE at 79 shops). Holding AP
headcount flat while growing to 150 shops requires AP effort per shop to fall by about **47%**
overall — and because reconciliation is only part of AP's workload, the reduction needed
*within reconciliation specifically* is materially higher, plausibly **75–80%**.

**The problem this system solves:** automate statement-to-record reconciliation to the point
that most statement lines require no human touch at all, so AP headcount doesn't have to grow
in lockstep with shop count.

**What this system explicitly must never do:** hold write authority over VIVE's financial
system of record. It proposes and matches; a human approves. This is a permanent design
position, not a v1 limitation to relax later.

---

## 2. The Governing Metric

**Straight-through rate** — the percentage of statement lines that reconcile with no human
touch — is the single metric this system is judged against. Three consequences follow
directly and should shape every build decision, not just the final threshold-tuning pass:

1. **Throughput is not the constraint.** Processing speed is not where engineering effort
   should go — correctness, explainability, and control are.
2. **A noisy exception queue is worse than no automation.** A wrong or low-value exception
   costs *more* AP time than a line that was never automated at all, because it forces a
   context switch and a judgment call. The system should decline to guess rather than
   produce a confident wrong answer.
3. **The business case is met by retiring entire exception categories** (e.g., turning
   "unexplained missing invoice" into "shop needs to post RO-59144" via corroborating data),
   not by incrementally tuning a confidence model.

**Prerequisite, not optional:** a manual baseline (lines per month, minutes per reconcile,
current first-pass failure rate) must be captured before build progress can be evidenced
against it at engagement close.

---

## 3. What The System Must Do

1. **Ingest** vendor statement PDFs — uploaded continuously, processed on a deliberate
   schedule (not the instant a file lands) — and track every document's status from
   upload through reconciliation.
2. **Extract** line-item invoice data from each statement automatically, with a mandatory
   arithmetic check (extracted lines must sum to the statement's stated total) before
   anything moves forward — this is the single highest-value control in the pipeline,
   since it catches extraction defects before they masquerade as business discrepancies.
3. **Pull in reference data VIVE already has** — open invoices from NetSuite and repair-order
   data from CCC — on a recurring internal schedule, so matching always runs against a
   known, versioned snapshot rather than calling either system live.
4. **Match** statement lines against that reference data — deterministic and reproducible
   first; a narrowly-scoped AI-assisted second opinion only on residual lines that don't
   resolve deterministically, and even then it never auto-approves, at any confidence level.
5. **Classify and route** anything that doesn't match into a tracked exception with an
   owner, a category, and an aging clock — with corroborating evidence (e.g. CCC repair-order
   confirmation) used to turn an ambiguous "we don't know what this is" into a specific,
   actionable instruction wherever possible.
6. **Group work into deliberate reconciliation runs** — a run has an explicit scope (period,
   vendor, legal entity, cutoff date), its inputs are frozen once created, and every match,
   exception, and approval traces back to the run that produced it. Re-running never silently
   overwrites a prior attempt — it creates a new, fully-traceable version.
7. **Give the AP team a review workspace** — approve or dispute individually or in bulk, see
   why the system suggested a match, and enforce a real separation between the person who
   reviews a match and the person who approves it, with a dollar threshold above which a
   second approver is required.
8. **Record every decision — automatic or human — permanently, as it happens.** Not logged
   after the fact.
9. **Report** reconciliation outcomes, exception trends, and processing cost to management,
   without that reporting ever competing for capacity with someone actively approving matches.

---

## 4. What The System Must Never Do (non-negotiables)

- Never let AI hold write authority over VIVE's books, at any confidence level, under any
  circumstance. AI proposes; deterministic rules decide; a human approves.
- Never call NetSuite or CCC live from the matching path — matching reads only a versioned,
  internally-owned snapshot, so a match is always reproducible against exactly the data it
  was evaluated against, independent of what either system says today.
- Never let statement intake itself trigger reconciliation. Ingestion and reconciliation
  execution are two separate, deliberate acts — a file landing in storage is not implicit
  scope for a run.
- Never overwrite a prior reconciliation attempt. Re-matching produces a new version; full
  history is preserved.
- Never let two reviewers silently clobber each other's work on the same exception or the
  same bulk-approval set.
- Never write reconciliation status back into NetSuite. **This one is currently in dispute
  — see §6, item 5 — the SOW names a write-back stage explicitly, but the current design has
  none. That conflict has to close before it's treated as settled either way.**

---

## 5. Definition of Success

Straight-through rate rises enough, evidenced against the captured manual baseline, that AP
effort per shop falls by the ~75–80% needed within reconciliation specifically (§2) — not
"the system looks like it's working." Success is not claimed until:

- A 3–4 month shadow-mode trial has run the system side-by-side with the AP team's current
  manual process for 3–4 full monthly cycles, with outcomes compared, before anything
  auto-approves.
- Confidence thresholds are set from what shadow mode actually measured, not guessed upfront.
- A named person on VIVE's side owns threshold review and system operation going forward —
  this system does not go live as an orphan.

---

## 6. Open Business Questions (gate the build — not to be resolved by assumption)

These are unresolved as of this brief and each has a named owner on the client or engagement
side. Build should not proceed past the point where a given item's answer is actually needed,
but none should be quietly assumed:

1. **Volume** — statements/month, lines, vendors, file sizes, growth trajectory. Can one PDF
   contain multiple statements? Does every vendor bill monthly, or do some bill weekly or
   biweekly? *(Owner: VIVE AP)*
2. **Is a daily (not real-time) re-match window acceptable**, or does the SOW's "auto
   re-match" language imply something faster? *(Owner: VIVE AP)*
3. **CCC parts-level data** — is it a source of truth, or does scope reduce to RO-level
   validation only? *(Owner: VIVE + engagement team)*
4. **NetSuite write-back — intentionally removed, or deferred?** The SOW names it explicitly;
   the current approved architecture has none. This is a direct conflict between source
   documents and must close before it's built either way. *(Owner: VIVE / SOW owner)*
5. **Is a monthly intake cadence acceptable across every vendor?** If any vendor's real
   statement cadence is faster than monthly, their statements wait weeks longer than
   necessary purely because of a scheduling assumption, not a technical constraint.
   *(Owner: VIVE AP)*
6. Confidence thresholds and auto-approve eligibility — deliberately not set until shadow
   mode produces real measurements. *(Owner: VIVE AP)*
7. Exception ownership, escalation ladder, and aging-clock semantics — including whether
   aging starts from the statement's own date or from discovery date, given intake latency.
   *(Owner: VIVE ops)*
8. Approval thresholds, second-approver rule, high-dollar threshold, data-retention policy.
   *(Owner: VIVE controller)*
9. Production ownership — subscription, cost center, on-call, runbooks, handover terms at
   engagement end. *(Owner: VIVE + engagement team — flagged explicitly as an organizational
   risk, not a technical afterthought, if left unnamed.)*
10. Network access model for the AP-facing workspace — public access with strong login
    controls vs. a fully private access model. Cost-viable either way; a security/networking
    decision, not an engineering one. *(Owner: VIVE IT)*

---

## 7. Explicitly Out of Scope (current design — not a permanent ban on all but one item)

- **Autonomous financial writes, at any confidence level.** Permanent — not a v1 limitation.
- **NetSuite write-back**, pending resolution of §6 item 4.
- **AI-assisted matching for the hardest residual cases** — designed for, but blocked on a
  governance sign-off unrelated to the technical build; always review-only even once unblocked.
- **Per-vendor deterministic parsers.** Universal extraction is the default; build a
  vendor-specific fast path only if real volume/cost data justifies it later.
- **Generated free-text suggested actions**, until rule-based suggestions prove insufficient.
- **Microservice decomposition.** A modular monolith plus workers is the deliberate choice
  at this scale.

---

## 8. Stakeholders

- **VIVE AP team** — primary users; owns volume, cadence, and threshold decisions.
- **VIVE Controller** — owns approval thresholds and retention policy.
- **VIVE IT** — owns network/access model and identity decisions.
- **SOW owner** — owns resolution of the write-back conflict (§6 item 4).
- **Engagement/build team** — Ayush Kumar Sinha, Vaishali Rao Yellur, and the wider IF-side
  team referenced in the approved architecture (Azure/infra escalation, CCC data ownership).
- **A named production owner on VIVE's side** — not yet assigned; required before go-live
  (§6 item 9).

---

## 9. Relationship to Existing Artifacts

- `docs/VIVE_Statement_Reconciliation_Architecture_v3_3.md` — the settled target technical
  architecture this brief traces to. Treat as the Explore/Decide output already produced
  outside PBVI; Phase 1 here validates against it rather than generating alternatives.
- `docs/VIVE_REBUILD_PLAN_TARGET_ARCHITECTURE.md` / `docs/VIVE_REBUILD_PLAN_BUSINESS.md` —
  the week-by-week and phase-by-phase build sequencing already agreed for delivering against
  v3.3, in a fresh repository.
- The prior application (`src/`, `web/`, etc. in this repository) is reference-only —
  working extraction/matching logic worth reading, not a codebase this brief inherits scope,
  gaps, or technical debt from.

---

## Engagement-Side Addendum (added 2026-08-27 — does not alter the original brief above)

Per `brief/`'s directory contract, this brief is never modified after receipt. The note
below is appended, not edited into, the original content, per PHASE4_GATE_RECORD.md
Finding 6.

**§7 supersession — per-vendor deterministic parsers.** §7 above lists "Per-vendor
deterministic parsers" as out of scope, with the stated test: *"Universal extraction is the
default; build a vendor-specific fast path only if real volume/cost data justifies it
later."* This build (EXECUTION_PLAN.md Session 3; ARCHITECTURE.md D-L) implements a
known-vendor deterministic (`pdfplumber`) extraction fast path alongside the Claude-primary
universal path — ahead of §7's own volume/cost test, not in response to it. This is a
knowing, engineer-directed decision, recorded here rather than by editing §7 itself. See
`docs/ARCHITECTURE.md` D-L for full rationale, the rejected alternative (stay
brief-compliant, universal-only, until §7's test is actually met), and the revisit
condition.

**Decision owner:** Vaishali. **Date:** 2026-08-27.

