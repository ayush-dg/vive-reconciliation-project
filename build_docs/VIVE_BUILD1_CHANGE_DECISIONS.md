# CHANGE_DECISIONS.md — Findings from the Fred Beans Investigation vs. the Signed-Off Build Docs

**Status:** DRAFT — decisions needed, not yet applied to any signed-off document.
**Purpose:** During manual reconciliation testing against a real vendor (Fred Beans Parts,
Lee's Auto Body statement, Oct 2025–Aug 2026 NetSuite history), several real-world patterns
surfaced that the signed-off ARCHITECTURE.md (v1.0), INVARIANTS.md (v1.2), and
EXECUTION_PLAN.md (v1.0) either don't account for, or account for in a way this evidence now
calls into question. This document lists each one as an open decision — what was found, why
it matters, what the current docs say, and the options — for Vaishali to decide before any
of those three documents are edited.

**This file changes nothing on its own.** Once decisions are made below, the affected
sections of ARCHITECTURE.md / INVARIANTS.md / EXECUTION_PLAN.md get updated to match.

---

## Decision 1 — Does the matching engine need paid/closed history, not just open invoices?

**What we found:** Of the 273 statement lines tested against Fred Beans, the large majority
of clean matches were against NetSuite bills already marked **Paid In Full** — not open
invoices. Reconciling a real vendor statement is fundamentally a check against history
("did we already account for this"), not primarily against an open-items list.

**What the current docs say:** ARCHITECTURE.md D-B adopts v3.3's D9 as-is: *"NetSuite and
CCC reference data ingested via an internally-owned daily batch job... "* — and
EXECUTION_PLAN.md Task 4.1 names the pull target explicitly as **"NetSuite open invoices."**
If that's taken literally, the reference Silver snapshot this build's matcher reads from
would not contain the paid bills that this investigation showed are most of what a
statement actually needs reconciled against.

**Tension:** This isn't a new architectural principle being introduced — D9 already exists
and is adopted as-is. The question is whether "open invoices" was ever meant literally, or
was shorthand that nobody had reason to interrogate before real vendor data was tested
against it.

**Options:**
- **A.** Expand the NetSuite pull (Task 4.1) to include a bounded historical window of
  closed/paid bills and credits (e.g., matching the statement lookback window), not just
  currently-open ones. Cheapest fix, same pull mechanism (SuiteQL bulk table pull), just a
  wider `WHERE` clause.
- **B.** Keep the pull scoped to open invoices only, and treat "reconcile against a vendor's
  full paid history" as explicitly out of scope for this build's matcher. Statement lines
  that resolve to closed bills would then always fall to Exceptions.

**Downstream impact if A is chosen:** EXECUTION_PLAN.md Task 4.1 (query scope). No
architecture-level change needed — this is a data-boundary widening under the existing D9,
not a new decision.

---

## Decision 2 — Vendor-to-NetSuite-entity-ID mapping is a missing data model piece

**What we found:** A single real-world vendor (Fred Beans Parts) maps to **7 distinct**
NetSuite `entity` IDs (different shop/subsidiary records for what a human calls one
vendor). Matching only against the one entity ID a statement names would have missed a
meaningful share of otherwise-real matches.

**What the current docs say:** ARCHITECTURE.md D-F's "entity" is a different concept —
`legal_entity_id` tags which of *VIVE's own* legal entities a document belongs to. There is
no existing entity in the §8 data model for "which NetSuite vendor-entity IDs correspond to
this one vendor." This is a genuine gap, not a naming clash to resolve — D-F does not cover
it either way.

**Options:**
- **A.** Add a lightweight `VendorEntityMap` (vendor name/ID → one or more NetSuite entity
  IDs) as a new first-class entity in §8, populated manually or semi-manually per vendor as
  they're onboarded.
- **B.** Defer entirely — treat this as a BCE-scope problem, and for this build, require the
  statement's own vendor identification to carry the single NetSuite entity ID to match
  against (accepting that cross-entity matches, like the ones we found, won't be caught).

**Recommendation:** A. This isn't a workflow feature deferral like D-C's review workspace —
it's a data-correctness gap that silently under-matches real invoices, the same category of
problem G2 exists to prevent on the extraction side.

**Downstream impact if A is chosen:** ARCHITECTURE.md §8 (new entity), EXECUTION_PLAN.md
Session 4 (a small ingestion/maintenance task for the map) and Task 5.2 (matching query
must fan out across all mapped entity IDs, not one).

---

## Decision 3 — Matching must check Vendor Credits, not only Vendor Bills

**What we found:** Statement lines are not all charges — a meaningful share are credit-column
entries, and several of those matched exactly against NetSuite Vendor Credit records (not
Bills). Matching only against bills would misclassify all of these as unmatched.

**What the current docs say:** EXECUTION_PLAN.md Task 5.2's CC prompt says: *"recon key is
vendor invoice number matched to NetSuite Bill document number."* No mention of Vendor
Credit.

**Options:**
- **A.** Task 5.2 matches statement lines against both Vendor Bill and Vendor Credit
  reference tables, keyed the same way (tranid/invoice number ↔ amount).
- **B.** Leave Bill-only matching and let all credit-column statement lines fall to
  Exceptions by default.

**Recommendation:** A — this is a correction to an existing task's scope, not a new
capability; the data model (§8's `ReferenceSnapshot`) already doesn't preclude pulling
credits too, it's just not named in the task prompt.

**Downstream impact if A is chosen:** EXECUTION_PLAN.md Task 4.1 (pull vendor credits
alongside bills) and Task 5.2 (match against both).

---

## Decision 4 — Duplicate-printing artifact needs explicit handling, not two independent line resolutions

**What we found:** In 38 confirmed cases, the *same* NetSuite bill was printed twice on the
statement — once as a charge, once later as a credit for the identical amount — with no
second real transaction behind it. Naively matching each line independently would either
double-count the match, or (worse) have one line match cleanly while its duplicate partner
gets misclassified as a stray/unexplained credit.

**What the current docs say:** Nothing — this pattern wasn't anticipated by any existing
invariant or task. S5 (exception category enum) has no category for it; Task 5.2/5.4 have
no logic for it.

**Options:**
- **A.** Add explicit duplicate-detection to Task 5.2: when a charge line and a credit line
  share an invoice number, an identical amount, and both resolve to the *same* underlying
  bill ID, treat them as one matched pair (new category, e.g. `DUPLICATE_STATEMENT_PRINT`),
  not two separate resolutions.
- **B.** Leave both lines to resolve independently and accept that this pattern will produce
  noisy but explainable exceptions for a human to interpret via the existing flat exception
  list.

**Recommendation:** A — given how common this turned out to be (38 of 182 distinct invoices
on one statement), leaving it to option B would flood the Exceptions list with a
high-volume, low-value noise pattern that a human would learn to ignore anyway — better to
name it explicitly.

**Downstream impact if A is chosen:** S5 (new enum value), EXECUTION_PLAN.md Task 5.2 (new
detection logic) and Task 5.4 (new category wiring).

---

## Decision 5 — Credit-memo name/RO-number similarity is not a valid matching signal

**What we found:** Every single credit memo we traced whose name or RO number appeared
related to a specific invoice actually turned out — when checked against NetSuite's real
application data — to have settled a *different*, unrelated bill. This was 100% consistent
across every case tested. Name/RO similarity is actively misleading here, not just weak
evidence.

**What the current docs say:** Task 5.3 (AI-assisted residual matching) already avoids
name-based inference and instead corroborates using CCC repair-order data — the RO-number
finding reinforces caution there but doesn't require a change to what's already planned.
Task 5.2 (deterministic matching), however, only checks bill/credit **existence and face
amount**, which is fine — the concern is making sure no *future* task is ever tempted to
use invoice-name or RO-number similarity as a proxy for "this credit settled this bill."

**What NetSuite actually requires to prove settlement:** the REST Record API's `/apply`
subresource on the paying-side record (Vendor Payment or Vendor Credit) — a per-record call,
not a bulk SuiteQL table pull. This is architecturally different from everything Session 4
currently plans (which is bulk daily-batch table snapshots).

**Options:**
- **A.** Add an explicit invariant/note (task-scoped, not necessarily Global) stating that
  invoice-name or RO-number similarity between a bill and a credit must never be treated as
  proof of settlement — only an `/apply`-sourced application record may be.
- **B.** Don't formalize this as an invariant; rely on it being self-evident from Task 5.2's
  narrow existence-and-amount scope, since nothing in the current plan proposes name-based
  settlement inference anyway.

**Recommendation:** A, but lightweight — a one-line task-scoped note attached to Task 5.2/5.3
referencing this finding, not a new Global invariant (it doesn't clear the five-cap bar; it
guards against a mistake nobody's currently proposing to make, closer to documentation than
enforcement).

**Downstream impact if A is chosen:** INVARIANTS.md (one new task-scoped note, not a Global
invariant) and a one-line addition to Task 5.2/5.3's CC prompts.

---

## Decision 6 — Should "prove what specifically settled this bill" be a build feature at all?

**What we found:** Going beyond "does this bill exist and does the amount match" to "which
exact payment or credit settled it" required the REST Record API `/apply` trace — a slow,
per-record, brute-force-search operation (e.g., sweeping every vendor payment for a vendor
across a date range) fundamentally unlike the bulk Silver-snapshot pattern the whole
architecture (D9, D-B) is built around.

**What the current docs say:** Nothing plans for this. D9/D-B's "never call the API live"
adoption, plus the already-flagged tension in INVARIANTS.md's Removed Invariants note
(engineer noted a *possible future* live-NetSuite matching mode, explicitly out of scope for
now), both point toward this being intentionally excluded from the bounded build.

**Options:**
- **A. Out of scope for this build.** The deterministic matcher only ever needs
  existence + amount + status (all available from the bulk Silver snapshot). "What
  specifically paid this" stays a manual/investigative capability (what we did by hand this
  session), not a built feature. Matches this build's existing boundary philosophy (D-A: bounded
  slice, defer the rest to BCE).
- **B. Add it as a scoped, separate on-demand task** (e.g., a new Task 5.5 / drill-down
  endpoint) — callable per-invoice, not run in bulk, explicitly exempted from D9's
  live-call restriction the same way the parking-lot entry already anticipates.

**Recommendation:** A for this build, explicitly logged as a parking-lot item (the
ARCHITECTURE.md §7 table already has a matching entry: *"Live NetSuite/CCC pull as an
alternative matching mode"* — this finding is corroborating evidence for why that item exists,
not a reason to pull it into this build's scope now).

**Downstream impact if A is chosen:** No document edits required beyond adding one sentence
to the existing §7 parking-lot row citing this investigation as the motivating evidence.
If B is chosen instead: EXECUTION_PLAN.md gets a new task, and ARCHITECTURE.md's D-B
adoption of D9 needs a carved-out exception noted explicitly (mirroring the Removed
Invariants tension already on file in INVARIANTS.md).

---

## Decision 7 — Exception/match categories need new values

**What we found:** The statement produced at least these distinct, real outcomes that don't
map cleanly onto a single "matched" or "unmatched" bucket:
- Matched, invoice closed, but the statement's dollar amount is stale (bill already
  paid/settled at a different figure than what's printed)
- Matched, invoice still open, and the amount genuinely differs (real discrepancy, not
  staleness)
- Matched, but only because of the duplicate-print artifact (Decision 4)
- A similarly-named credit memo exists but provably settled a *different* bill (Decision 5)
- Not found in NetSuite at all

**What the current docs say:** S5 requires a closed enum but doesn't enumerate its values;
Task 5.4 just says "wire exception-creation paths to the fixed category enum" without
specifying what's in it yet — this is likely the right place to settle it, not a doc that's
already wrong.

**Options:**
- **A.** Adopt a specific enum now (something like: `MATCHED`, `MATCHED_STALE_AMOUNT`,
  `MATCHED_AMOUNT_MISMATCH_OPEN`, `DUPLICATE_STATEMENT_PRINT`, `CREDIT_UNLINKED`,
  `NOT_POSTED`) informed directly by this investigation's real outcomes, rather than
  designing the enum in the abstract during Task 5.4.
- **B.** Leave enum definition to Task 5.4 as currently scoped, treating this investigation
  as informal input rather than a specification.

**Recommendation:** A — this investigation is exactly the kind of real-data evidence Task
5.4 would otherwise have to guess at; using it now avoids a rework once real statements hit
the built system and reveal the same categories anyway.

**Downstream impact if A is chosen:** EXECUTION_PLAN.md Task 5.4 (enum values specified
directly in the CC prompt) and S5 (example values added to the invariant text for clarity,
still a closed set, not free text).

---

## Summary Table

| # | Decision | Recommendation | Docs touched if adopted |
|---|---|---|---|
| 1 | Pull paid/closed history, not just open invoices | A (widen pull) | EXECUTION_PLAN.md Task 4.1 |
| 2 | Vendor→NetSuite-entity-ID mapping | A (add data model entity) | ARCHITECTURE.md §8, EXECUTION_PLAN.md Session 4 + Task 5.2 |
| 3 | Match against Vendor Credits too | A (both bill + credit) | EXECUTION_PLAN.md Task 4.1, 5.2 |
| 4 | Duplicate-print artifact handling | A (explicit detection + category) | INVARIANTS.md S5, EXECUTION_PLAN.md Task 5.2, 5.4 |
| 5 | Name/RO similarity is not proof of settlement | A (lightweight task-scoped note) | INVARIANTS.md (note only), EXECUTION_PLAN.md Task 5.2/5.3 |
| 6 | "What exactly settled this bill" as a feature | A (stays out of scope, log as parking-lot evidence) | ARCHITECTURE.md §7 (one sentence) |
| 7 | New exception/match category values | A (adopt concrete enum now) | EXECUTION_PLAN.md Task 5.4, INVARIANTS.md S5 |

---

## Next Step

Once Vaishali marks a recommendation (or an alternative) against each numbered decision
above, the corresponding edits get applied to ARCHITECTURE.md, INVARIANTS.md, and/or
EXECUTION_PLAN.md as a tracked revision (each with its own dated changelog note, consistent
with how the 2026-08-17 resequencing changes were recorded in EXECUTION_PLAN.md).