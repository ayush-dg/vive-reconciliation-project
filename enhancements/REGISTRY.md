# enhancements/REGISTRY.md — VIVE Reconciliation

> **PBVI-009 Brownfield Onboarding — Approximation Notice**
> Created as an empty starting file per an approximated PBVI-009 onboarding pass
> (`pbvi_brownfield.md` was unavailable — see `docs/ARCHITECTURE.md` for full notice).
> This system is not yet declared sprint-ready — per `pbvi_core.md`, PBVI-009
> onboarding is not itself the sprint-ready declaration, and no
> `discovery/ONBOARDING_LOG.md` attestation exists for this approximated pass.
> SPRINT-001 was initiated (Prompt 0) regardless, per direct engineer instruction —
> flagged here, not silently smoothed over.

**System:** VIVE Reconciliation
**Master index status:** 14 enhancements tracked (1 COMPLETE, 1 CANCELLED, 12 IN BACKLOG) — 1 sprint CLOSED, 0 open

> **2026-08-11 backlog intake:** 12 new enhancements (ENH-002–ENH-006, ENH-008–ENH-014
> — ENH-007 skipped, already used/cancelled) added from an initial engineer/teammate
> planning pass over the remaining roadmap. None have completed the Prompt 1 brief
> review gate yet — all are Draft stubs in `enhancements/backlog/`, same pattern as
> the original ENH-007 stub. See "Proposed Backlog Grouping" below for a non-binding
> sprint-sequencing recommendation; no `SPRINT-002` (or later) has been initiated —
> that's a separate, deliberate trigger, not implied by this registry update.

---

## Enhancement Index

| ENH ID | Title | Status | Sprint | Classification | Depends On | Collision Surfaces |
|---|---|---|---|---|---|---|
| ENH-001 | Automated batch intake pipeline (Blob Storage + Event Grid + batch_id) | COMPLETE | SPRINT-001 | [pending Prompt 2] | — | [pending Prompt 2] |
| ENH-002 | Run Management Layer | IN BACKLOG | — | [pending Prompt 2] | — | ENH-004 (flagged) |
| ENH-003 | Statement Processing / Work-Item Versioning | IN BACKLOG | — | [pending Prompt 2] | ENH-002 | — |
| ENH-004 | Finish the Fabric Migration | IN BACKLOG | — | [pending Prompt 2] | — | ENH-002, ENH-008 (flagged) |
| ENH-005 | Document Registry Completion | IN BACKLOG | — | [pending Prompt 2] | — | ENH-006 (flagged) |
| ENH-006 | Validation Service Hardening | IN BACKLOG | — | [pending Prompt 2] | — | ENH-005 (flagged) |
| ENH-007 | Match Confidence Score | CANCELLED | — | — | — | — |
| ENH-008 | Audit Ledger Unification | IN BACKLOG | — | [pending Prompt 2] | ENH-002 | ENH-004 (flagged) |
| ENH-009 | Pass 3 AI-Assisted Matching | IN BACKLOG (BLOCKED) | — | [pending Prompt 2] | Sprint Lead review of INV-02 amendment (`docs/Claude.md` v2.8) | — |
| ENH-010 | Access Control Hardening | IN BACKLOG | — | [pending Prompt 2] | — | — |
| ENH-011 | n8n Orchestration Wrapper | IN BACKLOG | — | [pending Prompt 2] | — | — |
| ENH-012 | Power BI / Gold Reporting | IN BACKLOG | — | [pending Prompt 2] | — | — |
| ENH-013 | Files/SharePoint Export | IN BACKLOG | — | [pending Prompt 2] | ENH-012 (soft) | — |
| ENH-014 | Email/Notification Alerts | IN BACKLOG | — | [pending Prompt 2] | ENH-002 (soft) | — |

Each new ENH-NNN's full brief lives at
`enhancements/backlog/ENH-NNN-<slug>/ENH-NNN_BRIEF.md`.

Status values: IN BACKLOG \| IN SPRINT \| IN EXECUTION \| COMPLETE \| CANCELLED

**ENH-001:** Status COMPLETE. `ENH-001_BRIEF.md` (`enhancements/SPRINT-001/ENH-001-automated-batch-intake/`)
is authored, passed the Prompt 1 brief review gate (PASS WITH ADVISORIES — one open
advisory: Enhancement Intent doesn't state business motivation, non-blocking), and is
**Signed Off** (2026-07-24). Build completed 2026-07-24/25; `ENH-001_BCE_IMPACT.md`
(same directory) documents the actual build against the brief, including that the
build's scope expanded well beyond what the brief specified (see that file's Scope
Note, "Build Deviated From Brief"). BCE gap detection could not run formally for
this enhancement — no `sessions/` Verification Record trail exists — so the impact
log is a documented substitute, not a formal close-out. Classification/Depends
On/Collision Surfaces were never resolved via Prompt 2 (collision surface analysis
never ran) and remain `[pending Prompt 2]` — marked COMPLETE anyway per direct
engineer instruction, not because that gap was resolved.

**ENH-007:** Status CANCELLED. Brief remains a Draft stub
(`enhancements/backlog/ENH-007-match-confidence-score/ENH-007_BRIEF.md`), never
signed off, never entered a sprint. Cancelled because the work it describes — a
deterministic, rule-based per-row/per-match confidence score — already shipped
under ENH-001 (commit `6685969`, "Step 7: Add match confidence scoring to matched
invoices and exceptions"), per `ENH-001_BCE_IMPACT.md`'s Scope Note ("Build
Deviated From Brief"), which documents this exact supersession.

---

## Proposed Backlog Grouping (2026-08-11, non-binding — pending Prompt 2 per sprint)

Recorded per direct engineer instruction alongside the 2026-08-11 backlog intake.
This is a sequencing recommendation to inform Prompt 2 collision-surface analysis
when each sprint is actually initiated — **it is not itself a Sprint Manifest and
does not substitute for running Prompt 2 on whichever enhancements a sprint
actually contains.** Team capacity for this backlog: 2-3 engineers building
concurrently, which is why collision-flagged pairs are kept in different proposed
groups below rather than assumed safe to build in parallel.

| Proposed Group | ENH IDs | Rationale |
|---|---|---|
| Next sprint | ENH-002, ENH-010, ENH-011, ENH-013, ENH-014 | ENH-002 is foundational and unblocked; the other four are independent of it and of each other, with no flagged collision |
| Sprint after ENH-002 lands | ENH-003, ENH-008, ENH-005 *or* ENH-006 (pick one), ENH-012 | ENH-003/ENH-008 unblock once ENH-002 ships; ENH-005↔ENH-006 are flagged as colliding, so only one goes in this group |
| Sprint after ENH-002 + ENH-008 land | ENH-004, plus whichever of ENH-005/ENH-006 wasn't picked above | ENH-004 collides with ENH-002 and ENH-008 — safe once those have already shipped, not built concurrently with them |
| Held, not scheduled | ENH-009 | Blocked on Sprint Lead review of the INV-02 amendment (`docs/Claude.md` v2.8) — see ENH-009's brief. Do not place in any sprint until that review lands. |

**Flagged for Prompt 2, not resolved here:** ENH-002↔ENH-004, ENH-004↔ENH-008,
ENH-005↔ENH-006. The grouping above avoids same-sprint collisions by sequencing;
if capacity/timeline pressure makes the sprint lead want two of these in the same
sprint after all, that requires explicit ownership/watchpoint assignment via
Prompt 2 collision-surface analysis, not a decision made in this registry.

---

## Sprint Index

| Sprint ID | Timebox | Sprint Lead | Status | Close-Out Date |
|---|---|---|---|---|
| SPRINT-001 | [not yet declared] → [not yet declared] | Ayush Kumar Sinha | CLOSED | 2026-07-28 |

Status values: OPEN \| INTEGRATION CHECK \| CLOSED
