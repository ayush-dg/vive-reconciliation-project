# INVARIANTS.md — VIVE Statement Reconciliation (Bounded First Build)

**Version:** 1.2 (pending engineer sign-off)
**Status:** DRAFT — awaiting sign-off per PBVI Human Accountability Gate
**Traces to:** ARCHITECTURE.md v1.0, UI_SURFACE.md v1.0, VIVE_Statement_Reconciliation_Architecture_v3_3.md
**Base document:** Engineer-authored (INVARIANTS2.md), merged with challenge-test-passing additions from a second engineer draft (invariants3.md)
**Authorship mode:** GOVERNED for this merge — engineer drafted first, CD challenged and merged

## Purpose

This document defines the invariants and preconditions for the bounded VIVE Statement
Reconciliation build. It deliberately separates:

1. **Global Invariants** — properties that must hold across the system, hard-capped at
   five per `pbvi_core.md` (Claude.md Section 2 ceiling — no override).
2. **Task-Scoped Invariants** — constraints applying to particular implementation tasks;
   embedded inline in EXECUTION_PLAN.md task prompts, not in Claude.md.
3. **Open Decisions / Preconditions** — unresolved design questions that must be answered
   before the affected implementation can be finalized.
4. **Deferred Target-State Invariants** — controls belonging to the future target
   architecture (BCE-scope), not the bounded build.

**Classification rule:** If any task in the execution plan could plausibly run without a
given invariant being relevant, it is TASK-SCOPED, not GLOBAL. GLOBAL is reserved for the
few constraints so cross-cutting and high-harm that Claude Code must hold them regardless
of which task it's executing.

An open decision is not treated as an invariant until the underlying behavior is decided.

---

# 1. Global Invariants (5 — hard cap)

## G1 — Extraction attempts belong to exactly one document, and are append-only (promoted from S9)

**Invariant:** `ExtractionAttempt.document_id` always references a valid Document. Once
written, an extraction attempt record is never modified — a subsequent attempt is a new
record, not an update to a prior one.

**Violation:** An extraction attempt exists with no valid parent document, or an existing
attempt record is mutated after the fact.

**Failure Mode:** Detection point — foreign key constraint (document_id); append-only
enforcement at the write layer (no UPDATE permitted on attempt rows once created).
Blast radius — loss of the audit trail G2/S10 depend on; an attempt history that can be
silently rewritten undermines the arithmetic-gate audit record entirely.

**Why GLOBAL:** Promoted 2026-08-17 to fill the slot vacated by the removed matching-live-call
invariant (see Removed Invariants note below). Reasserted as cross-cutting because the
audit trail it protects is relied on by G2 (validation gate) and by S10 (Bronze-before-
validation) — corruption here undermines both.

---

## G2 — No unvalidated extraction becomes match-eligible

**Invariant:** A document is never eligible for matching unless its latest extraction has
passed structural validation, arithmetic validation, and the extraction-confidence floor.

**Violation:** A document with failed arithmetic, structural validation, or insufficient
confidence becomes matching-eligible.

**Required behavior:**
```text
Extraction -> Validation -> PASS: eligible for matching
                          -> FAIL: retry / exception
```

**Failure Mode:** Detection point — validation gate check at the Silver-promotion boundary.
Blast radius — extraction defects masquerading as business discrepancies (per v3.3's
worked example: a dropped digit reaching AP as a false $6,000 mismatch).

**Why GLOBAL:** The single highest-value control in the entire pipeline per v3.3's own
framing — a violation here silently poisons every downstream task (matching, exceptions,
reporting) with corrupted data.

---

## G3 — Extracted content is model data, never model instructions

**Invariant:** Vendor/document content supplied to Claude must be treated strictly as input
data. Extracted content must never be concatenated into or allowed to modify the model's
instructions.

**Violation:** Document-controlled text alters the extraction prompt, system instructions,
tool instructions, or execution behavior.

**Why it matters:** A successful prompt-injection attack may still produce a plausible-
looking extraction and therefore cannot reliably be detected by downstream output
inspection alone.

**Failure Mode:** Detection point — code review checklist; prompt-template structural
separation enforced at the API-call layer. Blast radius — silently corrupted extraction
that passes all downstream checks, since injected content can be crafted to look valid.

**Why GLOBAL:** Security-critical and applies wherever any LLM call exists in the system,
not just one task — the harm (undetectable corrupted output) is severe and silent by
construction.

---

## G4 — Content-hash idempotency

**Invariant:** Byte-identical documents, identified by the same content hash, are never
independently re-extracted or re-matched.

**Violation:** The same PDF content is registered as a new processing unit and
independently sent through extraction or reconciliation.

**Required behavior:**
```text
same content_sha256 -> same logical document -> no second extraction/reconciliation
```

**Failure Mode:** Detection point — unique constraint on `content_sha256` at write time
(DB-enforced). Blast radius — duplicate extraction/matching work, inflated statement
counts on Home.

**Why GLOBAL:** Document identity is a foundational assumption every downstream component
(extraction, matching, Exceptions, Home) relies on without re-verifying — corruption here
propagates everywhere silently.

---

## G5 — Single active processing owner

**Invariant:** A document/work item cannot have multiple active processing owners
simultaneously. A retry or re-trigger must acquire processing ownership before execution;
an already-owned item must not be processed concurrently.

**Violation:** Two workers or triggers independently process the same document/work item
at the same time.

**Why it matters:** Single-role authentication does not imply single-writer processing.
Concurrent worker executions can cause duplicated extraction, duplicated matches,
conflicting state transitions, or doubled external model spend.

**Failure Mode:** Detection point — processing-lock/lease acquisition check before
execution begins. Blast radius — duplicated Claude API spend, conflicting state writes,
silently doubled processing cost.

**Why GLOBAL:** Spans both extraction and matching workers; a concurrency violation here
has system-wide financial and data-integrity consequences, not confined to one task.

**Implementation note:** Resolved 2026-08-17 (was OD2) — enforced via `recon`'s SQL
database in Fabric, using its native transactional/locking guarantees as the processing
ownership mechanism. This is not the full target-state `ROWVERSION` optimistic-concurrency
design (T1, still deferred) but the same underlying engine (Azure SQL Database engine)
provides sufficient locking support for this bounded build's single-active-owner
requirement.

---

# 2. Task-Scoped Invariants

*(Embedded inline in EXECUTION_PLAN.md task prompts at Phase 3, not in Claude.md Section 2.)*

## S1 — Upload does not trigger matching

**Invariant:** Upload/intake never implicitly triggers matching. Uploading a document may
register it for later discovery/processing, but matching must be initiated by the
explicitly defined processing mechanism.

**Violation:** An upload event directly causes a matching execution.

**Risk:** Matching may execute against incomplete or unintended input.

**Scope:** Intake and match-trigger tasks.

---

## S2 — Conflicting vendor/period/entity documents require review

**Invariant:** A non-identical document for an already-processed vendor/period/entity
combination must not be silently accepted alongside the first document. It must be
flagged for human decision before extraction proceeds. (Traces to D-H.)

**Violation:** A second, non-identical document is automatically processed as an unrelated
statement without recording the ambiguity.

**Scope:** Document intake / duplicate detection / document classification tasks.

**Resolution note:** Confirmed 2026-08-17 (OD4) — this build surfaces the flag read-only,
with no action button; actual resolution logic is deferred to a future decision.

---

## S3 — Reporting reads ReportView, not `recon`

**Invariant:** Reporting reads from the designated ReportView/Gold-equivalent surface and
does not query `recon` directly. (Traces to D-D.)

**Violation:** A report implementation joins or queries transactional `recon` tables
directly.

**Classification rationale:** Fails the harm-and-detectability test as a *global*
invariant today — the bounded build has no concurrent AP review workload, so a violation
causes no immediate observable harm. It remains task-scoped guidance because the
architecture intentionally isolates reporting from `recon` so the pattern doesn't become
expensive to unwind once concurrent review/approval workloads exist.

**Scope:** Report-building task.

---

## S4 — `legal_entity_id` requirement

**Invariant:** `bronze.document.legal_entity_id` must not be null.

**Violation:** A document is registered without a legal-entity assignment.

**Scope:** Document schema / ingestion task.

**Status:** Conditional — do not finalize until the entity-scoping decision is closed.
This invariant assumes a statement belongs to exactly one legal entity; if a statement can
span multiple entities/shops, this must be revised to a lower-granularity association
(e.g., statement line).

---

## S5 — Exception category is a closed enum

**Invariant:** `Exception.category` uses a fixed, approved set of categories and is never
arbitrary free text.

**Violation:** An exception is persisted with an unrecognized category string.

**Rationale:** A closed category set supports consistent downstream handling and preserves
the forward-compatible structure D-G requires.

**Scope:** Exception schema / matching / exception-handling tasks.

---

## S6 — Normalization version traceability

**Invariant:** If normalization rules change, historical matching can still identify which
normalization logic version was used.

**Classification rationale:** Fails the harm-and-detectability test as a global invariant
for this build specifically — there is no versioned normalization-rule-change scenario yet
in a first build. Retained as task-scoped implementation guidance for whoever eventually
builds the normalization layer, not enforced or tested as a global property now.

**Scope:** Normalization implementation task.

---

## S7 — Extraction attempts are bounded (demoted from G3)

**Invariant:** A document receives at most two extraction attempts before being flagged
`OCR_LOW_CONFIDENCE`.

**Violation:** A document is repeatedly submitted for extraction beyond the retry bound.

**Required behavior:**
```text
Attempt 1 -> failure -> Attempt 2 -> failure -> OCR_LOW_CONFIDENCE
```

**Classification rationale:** A task not touching the extraction retry loop (e.g., building
the Exceptions list UI) could plausibly run without this being relevant — demoted from
Global per the five-cap and the classification test.

**Scope:** Extraction service task.

---

## S8 — Reference data is version-bound (demoted from G6)

**Invariant:** Every Match and Exception that depends on reference data must reference
exactly one immutable `ReferenceSnapshot` version. Matching must never resolve reference
data from an unversioned or live source.

**Violation:** A match or exception has no snapshot reference, references multiple
snapshots ambiguously, or uses reference data that cannot be tied to the exact version
used for the decision.

**Classification rationale:** Applies specifically to the matching task; demoted from
Global per the five-cap.

**Scope:** Matching service task.

---

## S9 — [PROMOTED to G1 on 2026-08-17 — see Global Invariants section and Removed Invariants note]

---

## S10 — Bronze write precedes validation, never the reverse (demoted from G9)

**Invariant:** Every extraction attempt is written to Bronze before validation determines
its fate. Bronze must never contain only successful attempts.

**Violation:** A failed extraction attempt exists that was never written to Bronze, or
validation runs before the Bronze write completes.

**Why it matters:** Per D7/§8.2, Bronze records every attempt including failures — that is
the audit record. Reversing this order silently destroys the ability to diagnose why an
extraction failed.

**Classification rationale:** Applies specifically to the extraction service task; demoted
from Global per the five-cap.

**Scope:** Extraction service task.

---

## S11 — Statement-line amounts are immutable after extraction (demoted from G10)

**Invariant:** Once a StatementLine's amount is extracted and written to Silver, it is
never silently changed. A different value requires a new extraction attempt or document
version that explains where the new value came from.

**Violation:** An existing StatementLine's amount field is updated in place without a
corresponding new extraction attempt or document version.

**Classification rationale:** Applies specifically to the extraction/Silver-write task;
demoted from Global per the five-cap.

**Scope:** Extraction / Silver-write task.

---

# 3. Open Decisions / Preconditions

## OD1 — Matching invocation and batch scope [RESOLVED 2026-08-17]

**Resolution:** Matching may be invoked either as a manual run (on-demand trigger) or via
a scheduled batch job. Both mechanisms are supported in this bounded build.

**Note:** The exact scope definition for a scheduled batch run (which documents/date range
constitute "the batch") is not yet specified beyond this — if that level of detail is
needed before Phase 3 implementation, it should be raised as a follow-up question rather
than assumed.

---

## OD2 — Concurrent processing / single-writer mechanism [RESOLVED 2026-08-17]

**Resolution:** Enforced by `recon`'s SQL database in Fabric — see G5's updated
implementation note. The full target-state `ROWVERSION` optimistic-concurrency mechanism
(T1) remains a separate, deferred control on top of this.

---

## OD3 — D-G forward-compatible extension points [RESOLVED 2026-08-17]

**Resolution:** Nullable `owner`, `aging_started_at`, and `run_reference` columns are added
to `recon.exception` now, even while unused in this bounded build, per engineer direction.
This satisfies D-G's forward-compatibility goal concretely rather than leaving it as an
unfalsifiable principle.

**Status:** No longer open — the design decision has been made.

---

## OD4 — D-H duplicate/correction resolution workflow [RESOLVED 2026-08-17]

**Resolution:** The duplicate/correction flag is read-only in this bounded build — no
action button, no in-app resolution mechanism yet. It is visible in the Exceptions list
and Exception Detail exactly like any other exception, but nothing can be done to it from
the UI. The actual resolution logic and mechanism (explicit supersession, additive-
statement handling, or another approach) is deliberately deferred to a future decision,
not an oversight.

**Tension resolved:** This removes the earlier flagged conflict with D-C (no review-
workspace actions in this build) — since no action surface is added at all, there's no
overlap with the deferred review/approval workspace boundary. "In the application" now
means the flag is *visible* in-app, not that in-app *resolution* exists yet.

**Note:** Resolution presumably happens outside the system for now (e.g., a direct
database correction, or an out-of-band AP process) until BCE builds the real workflow —
this bounded build does not need to specify how, since it adds no mechanism either way.

---

## OD5 — User/entity access model [PARTIALLY RESOLVED 2026-08-17]

**Resolution:** Confirmed — there will be multiple named users, not a single internal
operations user. This resolves the headcount question raised by the original open
decision.

**Interpretation applied (flagged, not silently assumed):** Multiple users are read here
as sharing the single existing role from ARCHITECTURE.md's D-E — this does NOT reopen the
"no role differentiation" decision, since no review/approval workspace exists yet to
differentiate permissions against. If actual distinct roles/permissions were intended
instead of multiple people sharing one role, this needs explicit correction.

**Still open:** Real per-user authentication/identity (not a single shared credential) is
now clearly required given multiple named users — this reinforces the relevance of D-F's
deferred entity-scoped access question (all-entities-at-once vs. per-user scoped view),
which was pushed to UI Discovery and remains unresolved there.

---

# 4. Deferred Target-State Invariants (BCE-scope)

These belong to the full target architecture and are deliberately not required as global
invariants for the bounded build. They must not be represented as though already enforced.

## T1 — Optimistic concurrency with `ROWVERSION`
Mutable Match and Exception records use database-enforced `ROWVERSION`; stale writes are
rejected rather than silently overwritten. (v3.3 D12.)

## T2 — Segregation of duties
The preparer cannot approve their own work, and AI can never be an approver.

## T3 — Multi-level approval
Reconciliation decisions above a configured dollar threshold require a second human
approval.

## T4 — Immutable financial audit ledger
Every financial decision and human action is captured in an append-only audit ledger
containing full decision context (run/work-item/document/line identity, source and
extracted values, candidates, rules, AI metadata, confidence, human decision, reviewer,
final status).

## T5 — Immutable reconciliation history
Re-match and correction operations create new Work Item versions rather than overwriting
historical results. (v3.3 D20.)

## T6 — Frozen Run scope and inputs
Once a Run is frozen, its document scope, ERP snapshots, rules, prompts, and model
versions cannot silently change. (v3.3 D18/D19.)

## T7 — Approval actions are individually reversible
Every bulk approval action is independently reversible, with the original action and
reversal retained in audit history.

---

---

## Removed Invariants (engineer-directed change)

**G1 (original) — "Matching uses Silver only / never calls NetSuite or CCC live" — REMOVED
2026-08-17 at engineer's direction.**

**Reason given:** A future feature may involve live NetSuite pulling/matching. Engineer
confirmed this feature is **not** part of the current bounded build — it is a future/
BCE-scope idea only.

**Flagged conflict (per Loop rule — not resolved silently):** This removal directly
reopens ARCHITECTURE.md v1.0's decision D-B, which explicitly adopted v3.3's D9 ("NetSuite
and CCC reference data ingested via an internally-owned daily batch job... matching never
calls either API live") as-is for this bounded build. Removing this as a Global invariant
means the bounded build, as currently specified, no longer has an explicit invariant
preventing live matching calls — even though the live-pull feature itself is confirmed
out of scope for this build. ARCHITECTURE.md should be amended with a corresponding note
(recommended: add a Deferred/parking-lot entry mirroring the "T8" suggestion made during
this discussion) so the two documents don't silently diverge. This has not yet been done
to ARCHITECTURE.md as of this INVARIANTS.md revision — flagging as an open follow-up.

**Replacement:** S9 (extraction attempt FK/append-only) was promoted to fill the vacated
Global slot, at engineer's selection among offered candidates (S7, S8, S9, or other).

---

# 5. Classification Summary

| Category | IDs |
|---|---|
| **Global Invariants (hard cap = 5)** | G1(promoted from S9)–G5 |
| **Task-Scoped Invariants** | S1–S8, S10, S11 (S9 promoted to G1) |
| **Open Decisions / Preconditions** | OD1 (resolved), OD2 (resolved), OD3 (resolved), OD4 (resolved), OD5 (partially resolved) |
| **Deferred Target-State Invariants (BCE-scope)** | T1–T7 |

## Guiding rule

> Do not promote an unresolved design decision into an invariant.

An invariant describes a behavior the system has already decided must always hold. An
open decision describes behavior the architecture has not yet decided. A deferred
target-state invariant describes a control valid for the eventual system but intentionally
outside the bounded build. GLOBAL status is reserved for the five invariants so
cross-cutting and high-harm that every task, regardless of what it builds, must respect
them — everything else, however important within its own task, is TASK-SCOPED.

---

## Provenance Note

G1–G5 and S1/S2/S3/S4/S5/S6 (originally G1–G7, S2/S6/S7, D1, D3 in the engineer's
INVARIANTS2.md draft) passed all six challenge tests. S7–S11 (originally G3, G6, G8, G9,
G10) also passed all six tests but were reclassified from Global to Task-Scoped to respect
the hard five-invariant cap, per the classification rule restated by the engineer: if any
task could plausibly run without the invariant being relevant, it is task-scoped. G8–G10's
underlying content (now S9–S11) originates from a second engineer draft (invariants3.md —
E1, E2, E7, and line-amount immutability respectively); N1–N3 also originated there, with
N3 reclassified as task-scoped (S6) per the harm-and-detectability test. The remainder of
invariants3.md (Run, audit ledger, ROWVERSION, approval, and shop-level security
invariants) was excluded entirely — it describes the full v3.3 target architecture, not
this bounded build, and belongs in BCE's eventual target-state invariant set.

## Engineer Sign-Off

**Decision owner:** Vaishali
**Date:** 2026-08-17
**Signature / confirmation:** [x] I confirm every invariant above has passed all five
challenge tests (goal vs. constraint, enforcement scope, bundling, coverage, harm and
detectability) plus the complexity accumulation test, the Global set respects the
five-invariant hard cap, and I stand behind this set.

**Signed off with open items carried forward to Phase 3 (not blocking):**
- OD3 and OD4 — RESOLVED 2026-08-17, no longer carried forward.
- OD5 — partially resolved; entity-scoped access model remains genuinely open.
