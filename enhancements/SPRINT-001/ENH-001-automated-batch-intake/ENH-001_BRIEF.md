# ENH-001_BRIEF.md

**Enhancement ID:** ENH-001
**Title:** Automated Batch Intake Pipeline
**Author:** Ayush Kumar Sinha
**Date:** 2026-07-24
**Status:** [ ] Draft | [ ] AI Review Complete | [x] Signed Off

---

## Enhancement Intent

Automated batch intake pipeline: Blob Storage drop-zone container + Event Grid
file-detection trigger + batch_id grouping for files arriving in the same drop
event. Treated as one combined enhancement since the three pieces only function
together — Event Grid detection requires the Blob Storage container to exist,
and batch_id grouping depends on knowing which files Event Grid reported as
arriving together.

---

## Known Touch Points

| Touch Point | BCE Artifact | Entry |
|---|---|---|
| Azure Blob Storage drop-zone container (new) | INTEGRATION_CONTRACTS.md / TOPOLOGY.md A03 | IP-009 — extends existing entry, which today only archives already-processed PDFs; this adds a new inbound use |
| Event Grid trigger/subscription (new) | INTEGRATION_CONTRACTS.md | NEW — no existing IP-NNN entry; not currently in INTEGRATION_CONTRACTS.md. **Confirmed at brief review gate (2026-07-24): this is genuinely a new integration point being introduced by this enhancement, not a legibility failure or terminology mismatch against something already modeled. Acceptable to proceed with it recorded as NEW.** |
| `web/routers/upload.py` (modified) or new equivalent entry point | ID_REGISTRY.md / MODULE_CONTRACTS.md | M-007 (upload router) — needs an Event-Grid-triggered path creating jobs, parallel to the existing manual upload flow |
| `jobs` table / `create_job()` in `web/queries.py` (modified) | ID_REGISTRY.md / MODULE_CONTRACTS.md | M-011 (web query layer) — needs a new `batch_id` field and grouping logic |
| `web/worker.py` (possibly touched) | ID_REGISTRY.md / MODULE_CONTRACTS.md | M-013 (background job worker) — only if batch-level status tracking is needed; not confirmed |

---

## Known Constraints

| Constraint | Type | Notes |
|---|---|---|
| Must not modify or replace the existing manual upload path in `web/routers/upload.py` | MANDATORY | This adds a new automated entry point alongside it |
| `batch_id` grouping must not rely on a time-window heuristic (e.g., "files uploaded within N seconds of each other") — it must derive from a reliable signal of which files arrived together in one drop event | MANDATORY | Reframed 2026-07-24 at brief review gate: the original wording ("must derive from Event Grid's actual delivery event") named a specific mechanism as if it were the business rule itself. The actual constraint is the reliability property (no time-window heuristic), not the mechanism that delivers it. |
| Whether `batch_id` is a new `jobs` table column or a separate linking table | OPTIONAL | Phase 1 design decision |
| The specific mechanism used to satisfy the reliable-grouping-signal constraint above (Event Grid, a manifest file included in the drop, a Storage Queue batching pattern, etc.) | OPTIONAL | Phase 1 design decision — not fixed here |

---

## Out of Scope

- Parallel/concurrent worker processing (separate enhancement — touches IC-19 /
  the single-PROCESSING-job invariant)
- Match confidence score (ENH-007, held separately)
- Batch-completion email/Excel alerts
- Bulk-approve review UI
- Changes to existing per-file failure handling — the current pipeline already
  marks a bad PDF as FAILED per job; this enhancement doesn't change that
  behavior, it just ensures batches contain independently-failing jobs

---

## Engineer Sign-Off

[x] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**Signed:** Ayush Kumar Sinha
**Date:** 2026-07-24
