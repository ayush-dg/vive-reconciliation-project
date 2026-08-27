# INVARIANTS.md

## Purpose

This document defines the invariants and preconditions for the **bounded VIVE Statement Reconciliation build**.

The document deliberately separates:

1. **Global Invariants** — properties that must hold across the system and are candidates for centralized enforcement/testing.
2. **Task-Scoped Invariants** — constraints that apply to particular implementation tasks or architectural boundaries.
3. **Open Decisions / Preconditions** — unresolved design questions that must be answered before the affected implementation can be finalized.
4. **Deferred Target-State Invariants** — controls belonging to the future target architecture rather than the bounded build.

An open decision is **not** treated as an invariant until the underlying behavior has been decided.

---

# 1. Global Invariants

These invariants represent the highest-value correctness, security, reproducibility, and integrity properties of the bounded system.

## G1 — Matching uses Silver only

**Invariant**

> Matching reads only the synced, versioned Silver snapshot. It never calls NetSuite or CCC live.

The matching path must have no live dependency on the NetSuite or CCC APIs.

**Violation**

A matching execution makes a live NetSuite/CCC call or resolves reference data outside the synced Silver snapshot.

**Why it matters**

A live lookup makes the result dependent on external system state and prevents reliable reproduction of the decision.

**Scope**

Global — applies to all matching executions.

---

## G2 — No unvalidated extraction becomes match-eligible

**Invariant**

> A document is never eligible for matching unless its latest extraction has passed the required structural validation, arithmetic validation, and extraction-confidence floor.

A failed validation must not silently progress downstream.

**Violation**

A document with failed arithmetic, structural validation, or insufficient extraction confidence becomes matching-eligible.

**Required behavior**

```text
Extraction
    ↓
Validation
    ├── PASS → eligible for matching
    └── FAIL → retry / exception
```

The architecture defines arithmetic, structural, and confidence checks as the extraction gate. 

**Scope**

Global.

---

## G3 — Extraction attempts are bounded

**Invariant**

> A document receives at most two extraction attempts before being flagged `OCR_LOW_CONFIDENCE`.

**Violation**

A document is repeatedly submitted for extraction beyond the permitted retry bound.

**Required behavior**

```text
Attempt 1
   ↓ failure
Attempt 2
   ↓ failure
OCR_LOW_CONFIDENCE
```

This prevents unbounded model retries and uncontrolled processing cost. The architecture explicitly specifies a maximum of two attempts. 

**Scope**

Global.

---

## G4 — Extracted content is model data, never model instructions

**Invariant**

> Vendor/document content supplied to Claude must be treated strictly as input data. Extracted content must never be concatenated into or allowed to modify the model's instructions.

**Violation**

Document-controlled text can alter the extraction prompt, system instructions, tool instructions, or execution behavior.

**Why it matters**

A successful prompt-injection attack may still produce a plausible-looking extraction and therefore cannot reliably be detected by downstream output inspection alone.

**Scope**

Global.

---

## G5 — Content-hash idempotency

**Invariant**

> Byte-identical documents, identified by the same content hash, are never independently re-extracted or re-matched.

**Violation**

The same PDF content is registered as a new processing unit and independently sent through extraction or reconciliation.

**Required behavior**

```text
same content_sha256
        ↓
same logical document
        ↓
no second extraction/reconciliation
```

The architecture uses `content_sha256` as the discovery idempotency key and explicitly deduplicates identical-file re-uploads. 

**Scope**

Global.

---

## G6 — Reference data is version-bound

**Invariant**

> Every Match and Exception that depends on reference data must reference exactly one immutable `ReferenceSnapshot` version. Matching must never resolve reference data from an unversioned or live source.

**Violation**

A match or exception has no snapshot reference, references multiple snapshots ambiguously, or uses reference data that cannot be tied to the exact version used for the decision.

**Why it matters**

The system must be able to reproduce what reference data was available when the decision was made.

**Scope**

Global.

---

## G7 — Single active processing owner

**Invariant**

> A document/work item cannot have multiple active processing owners simultaneously. A retry or re-trigger must acquire processing ownership before execution; an already-owned item must not be processed concurrently.

**Violation**

Two workers or triggers independently process the same document/work item at the same time.

**Example**

```text
Worker A → document X → processing
Worker B → document X → processing
                     ❌
```

**Why it matters**

Single-role authentication does not imply single-writer processing. Concurrent worker executions can cause duplicated extraction, duplicated matches, conflicting state transitions, or doubled external model spend.

**Scope**

Global.

**Implementation note**

The bounded build does not require the full target-state `ROWVERSION` design to enforce this. A suitable processing ownership/locking mechanism is sufficient for this invariant.

---

# 2. Task-Scoped Invariants

These constraints apply to specific implementation areas. They should be enforced within the relevant task rather than treated as universal system-wide invariants.

## S2 — Upload does not trigger matching

**Invariant**

> Upload/intake never implicitly triggers matching.

Uploading a document may register it for later discovery/processing, but matching must be initiated by the explicitly defined processing mechanism.

**Violation**

An upload event directly causes a matching execution.

**Risk**

Matching may execute against incomplete or unintended input.

**Scope**

Intake and match-trigger tasks.

---

## S6 — Conflicting vendor/period/entity documents require review

**Invariant**

> A non-identical document for an already-processed vendor/period/entity combination must not be silently accepted alongside the first document. It must be flagged for human decision before extraction proceeds.

**Violation**

A second, non-identical document is automatically processed as an unrelated statement without recording the ambiguity.

**Scope**

Document intake / duplicate detection / document classification tasks.

**Open dependency**

The exact mechanism for resolving this flag remains an open decision and is captured under **OD4**.

The architecture explicitly identifies this same-vendor/period/entity collision as requiring human review rather than silent acceptance. 

---

## S7 — Reporting reads ReportView, not `recon`

**Invariant**

> Reporting reads from the designated `ReportView`/Gold-equivalent reporting surface and does not query `recon` directly.

**Violation**

A report implementation joins or queries transactional `recon` tables directly.

**Scope**

Report-building task.

**Classification**

Task-scoped implementation guidance rather than a Global Invariant.

**Rationale**

The bounded build does not currently have concurrent AP review workload, so a violation does not create immediate observable harm. However, the architecture intentionally isolates reporting from `recon` so that the pattern does not become expensive to unwind when concurrent review/approval workloads are introduced. 

---

## D1 — `legal_entity_id` requirement

**Invariant**

> `bronze.document.legal_entity_id` must not be null.

**Violation**

A document is registered without a legal-entity assignment.

**Scope**

Document schema / ingestion task.

**Precondition**

This invariant assumes a statement/document belongs to exactly one legal entity.

If the unresolved entity-scoping question determines that a statement can span multiple entities or shops, this invariant must be revised to place the entity association at the appropriate lower-granularity level, such as the statement line.

**Status**

Conditional — do not finalize until the entity-scoping decision is closed.

---

## D3 — Exception category is a closed enum

**Invariant**

> `Exception.category` uses a fixed, approved set of categories and is never arbitrary free text.

**Violation**

An exception is persisted with an unrecognized category string.

**Scope**

Exception schema / matching / exception-handling tasks.

**Rationale**

A closed category set supports consistent downstream handling and preserves the intended forward-compatible structure.

---

# 3. Open Decisions / Preconditions

These are not invariants. They are architectural decisions that must be resolved before the affected behavior can be implemented or its invariant can be finalized.

## OD1 — Matching invocation and batch scope

**Question**

> How is matching actually invoked and what is the scope of a matching execution in the bounded build?

The architecture establishes that ingestion and processing are deliberately decoupled, but the bounded build does not yet fully specify whether matching is initiated by:

* a timer,
* a manual action,
* a scheduled batch,
* a per-document trigger,
* or another mechanism.

It also does not fully define what constitutes the input batch for a matching execution.

**Why this must be resolved**

Without a defined invocation and scope, invariants concerning matching boundaries, ownership, and processing completeness cannot be made precise.

**Required before**

Phase 3 matching implementation.

---

## OD2 — Concurrent processing / single-writer mechanism

**Question**

> What mechanism enforces G7's single-active-processing-owner invariant?

The architecture distinguishes between:

* a single application role, and
* concurrent processing by multiple processes/workers.

A single user role does **not** guarantee single-writer execution.

**Required decision**

Select the bounded-build mechanism for preventing concurrent processing of the same document/work item, such as an explicit processing lock/lease or equivalent database-backed ownership mechanism.

The full target-state `ROWVERSION` optimistic-concurrency mechanism is a separate deferred control.

---

## OD3 — D-G forward-compatible extension points

**Question**

> What specific nullable columns, extension points, or schema structures are required to support the intended future compatibility?

The forward-compatibility goal cannot itself be expressed as a meaningful invariant until the actual extension points are selected.

**Required before**

The relevant schema is finalized.

**Status**

Open; do not invent an invariant until the design decision is made.

---

## OD4 — D-H duplicate/correction resolution workflow

**Question**

> How does a human resolve a non-identical document that conflicts with an already-processed vendor/period/entity combination?

The current invariant only establishes:

```text
possible duplicate/correction
        ↓
human decision required
```

It does not yet define whether resolution happens:

* in the application,
* through an external AP process,
* through explicit supersession,
* through additive-statement handling,
* or through another mechanism.

**Required before**

The resolution invariant and corresponding implementation can be finalized.

---

## OD5 — User/entity access model

**Question**

> Is the assumed single internal operations user actually the correct user/access model for the bounded build?

The current assumption is effectively:

```text
single role
    +
internal operations user
```

If that assumption is incorrect—for example, if AP users or users associated with specific shops/entities will access the application—then additional authentication and authorization invariants will be required.

**Status**

Conditional; do not finalize entity-scoping/access invariants until the user model is confirmed.

---

# 4. Deferred Target-State Invariants

These controls belong to the **full target architecture** and are deliberately not required as global invariants for the bounded build.

They should not be represented as though they are already enforced.

## T1 — Optimistic concurrency with `ROWVERSION`

Target state:

> Mutable Match and Exception records use database-enforced `ROWVERSION`; stale writes are rejected rather than silently overwritten.

The target architecture explicitly specifies this behavior. 

---

## T2 — Segregation of duties

Target state:

> The preparer cannot approve their own work, and the AI can never be an approver.

The full AP workspace specifies approver/preparer separation and explicitly excludes AI from approval authority. 

---

## T3 — Multi-level approval

Target state:

> Reconciliation decisions above the configured dollar threshold require a second human approval.

The threshold and approval policy must be explicitly configured before this becomes an active invariant.

---

## T4 — Immutable financial audit ledger

Target state:

> Every financial decision and human action is captured in an append-only audit ledger containing the exact decision context.

The target `audit_ledger` records run/work-item/document/line identity, source and extracted values, candidate records, rules, AI metadata/output, confidence, human decision, reviewer, and final status. 

---

## T5 — Immutable reconciliation history

Target state:

> Re-match and correction operations create new Work Item versions rather than overwriting historical results.

The target architecture defines versioned Work Items with a history chain. 

---

## T6 — Frozen Run scope and inputs

Target state:

> Once a reconciliation Run is frozen, its document scope, ERP snapshots, rules, prompts, and model versions cannot silently change.

The target Run model explicitly binds these inputs to the Run ID at freeze time. 

---

## T7 — Approval actions are individually reversible

Target state:

> Every bulk approval action is independently reversible, with the original action and reversal retained in the audit history.

The target AP workspace specifies this as a required guard for bulk approval. 

---

# 5. Classification Summary

| Category                             | IDs                |
| ------------------------------------ | ------------------ |
| **Global Invariants**                | G1–G7              |
| **Task-Scoped Invariants**           | S2, S6, S7, D1, D3 |
| **Open Decisions / Preconditions**   | OD1–OD5            |
| **Deferred Target-State Invariants** | T1–T7              |

## Guiding rule

> **Do not promote an unresolved design decision into an invariant.**

An invariant describes a behavior that the system has already decided **must always hold**.

An open decision describes behavior that the architecture **has not yet decided**.

A deferred target-state invariant describes a control that is valid for the eventual system but **is intentionally outside the bounded build**.

This keeps `INVARIANTS.md` testable and prevents unresolved architecture questions from being disguised as requirements.


