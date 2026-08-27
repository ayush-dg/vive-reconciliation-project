# ENH-001_BCE_IMPACT.md

## Header
Enhancement: ENH-001 — Automated Batch Intake Pipeline
Engineer: [LEAVE BLANK — engineer fills]
Phase 8 sign-off date: [LEAVE BLANK]
BCE close-out date: [LEAVE BLANK]
Sprint: SPRINT-001

## BCE Gap Detection
Status: NOT CLEAN — FORMAL GAP DETECTION COULD NOT RUN

Per `BCE/bce_core.md` Section 14.1, formal gap detection requires Verification
Records under `sessions/` and an enhancement execution plan. Neither exists
for this project — confirmed by direct filesystem search (2026-07-28). A
best-effort substitute (reading `ENH-001_BRIEF.md`, `SPRINT-001_MANIFEST.md`,
`SPRINT-001_LOG.md`, and the 2026-07-24/25 git log against
`discovery/MODULE_CONTRACTS.md`) was performed instead and is the basis for
the Scope Note below. **This file is therefore itself outside the normal
generation sequence** — `bce_core.md` Section 14.2 states "Do not produce
ENH-NNN_BCE_IMPACT.md until the engineer confirms all gaps are resolved,"
and that confirmation was never obtained because formal gap detection never
ran. Being produced now anyway, at explicit engineer request, as a partial
record — not a completed BCE close-out artifact.

---

## Scope Note — Build Deviated From Brief

`ENH-001_BRIEF.md` scoped this enhancement as three things only: the Blob
drop-zone container, the Event Grid trigger, and `batch_id` grouping. The
brief explicitly marked **Out of Scope**: parallel/concurrent worker
processing ("separate enhancement — touches IC-19"), match confidence score
("ENH-007, held separately"), and bulk-approve review UI. Exception
routing/aging was never mentioned anywhere in the brief — not built, not
excluded, not discussed either way.

All four of those — parallel worker pool, match confidence scoring,
bulk-approve UI, and exception routing/aging — were built in the same
2026-07-24/25 window, under the ENH-001 label, per commits `08ffcda`
("Step 5: Replace single worker with parallel worker pool"), `6685969`
("Step 7: Add match confidence scoring to matched invoices and exceptions"),
`f004eae` ("Step 10: Add bulk approve for high-confidence exceptions"), and
`4537ca5` ("Step 8: Add routing and aging to exceptions").

**Consequence:** `ENH-007` ("Match Confidence Score") remains open in
`enhancements/REGISTRY.md` (Status: IN BACKLOG) describing work that has
already shipped, under a different enhancement's label, per commit
`6685969` above. This needs its own resolution — either cancel ENH-007 with
a reference to this note, or determine that ENH-007 actually covers
something distinct from what shipped (in which case that distinction should
be stated explicitly, since as currently written the two describe the same
mechanism: a deterministic, rule-based per-row/per-match confidence score).

**This is not a code defect.** The features that shipped are real, tested,
and are now documented in `discovery/MODULE_CONTRACTS.md` and the component
files it indexes (M-013, M-036, M-045, M-047, M-048, and the rewritten
B02/B03/G03 contracts). The gap is procedural: this scope expansion was
never captured in a brief revision, a collision-surface re-analysis, or a
DRIFT item. `SPRINT-001_MANIFEST.md` and `SPRINT-001_LOG.md`'s own
incomplete state — both stalled at "Sprint CC Initiation," never reaching
collision surface analysis (Prompt 2) or sprint close-out — is a
contributing cause, not a coincidence: the process step whose entire
purpose is catching exactly this kind of scope drift never ran.

---

## 1. TOPOLOGY.md Impact
Status: AFFECTED

### External System Boundary Map (A03)
Status: AFFECTED
| External System | Change Type | Before State | After State | Operational Notes |
|---|---|---|---|---|
| IP-010 (Azure Event Grid auto-intake webhook) | ADDED | No IP-010 record existed | Full A03 record present: called by M-046, auth via `VIVE_EVENTGRID_WEBHOOK_SECRET` (code-complete, not yet deployed), container hard-pinned, 100-event cap | Registered as part of the 2026-07-25 scoped refresh |

### A02 Section 4 — STAGE-2-DIVERGENCE Findings
Status: AFFECTED
| Boundary | Change Type | Before State | After State | Operational Notes |
|---|---|---|---|---|
| Job-claim guard scope (IC-19) | ADDED (finding #5) | Not recorded as a divergence in TOPOLOGY.md | Finding #5 added: confirms the system-wide → per-`pdf_filename` narrowing is engineer-approved (2026-07-24) and "not open," not a new question | This is documentation catching up to an already-made engineering decision, per the finding's own text |

Confidence: LOW
Notes: Content is directly sourced from the committed TOPOLOGY.md text (verified by direct read/grep this session, including a targeted grep for "IC-19"/"system-wide"/"pdf_filename" to confirm exact wording). The LOW rating reflects that this Before/After framing rests on the substitute brief-vs-built cross-reference used in place of formal gap detection — no `sessions/` Verification Record exists to independently corroborate it — not on any doubt about the file content itself.

## 2. MODULE_CONTRACTS.md Impact
Status: AFFECTED

### Cross-Cutting Finding #1 (Confidence fabrication tracking)
Change Type: MODIFIED
| Field | Before State | After State | Operational Notes |
|---|---|---|---|
| Finding text | Stated M-023 (`claude_sonnet_client.py:521`) hardcodes `ROW_CONFIDENCE = 0.75` alongside M-024/M-025/M-026, with no fix noted | States M-023 was fixed 2026-07-24 — it now elicits and parses a genuine per-row confidence value (see RISK_REGISTER.md R-001); M-024/M-025/M-026 still hardcode 0.75 | Finding was stale relative to RISK_REGISTER.md's own R-001 fix note, which had already documented the fix; the stale `:521` line citation for M-023 was dropped rather than guessed at a new line number |

### M-023 (Claude Sonnet 4.6 client) — confidence-fix propagation
Change Type: MODIFIED
| Field | Before State | After State | Operational Notes |
|---|---|---|---|
| Invariants Enforced | Not reflected as enforcing IC-15 or IC-20 anywhere in MODULE_CONTRACTS.md's own narrative | Cross-cutting finding #1 (above) now states M-023 preserves genuine model-elicited confidence and received the totals-row filter | The canonical Owning/Enforcing-module fields for IC-15/IC-20 live in INVARIANT_CATALOGUE.md (Section 4 below); this entry is MODULE_CONTRACTS.md's own narrative-level record of the same underlying fact |

Confidence: LOW
Notes: Same basis as Section 1 — directly sourced from the committed MODULE_CONTRACTS.md text, cross-checked against RISK_REGISTER.md's R-001 fix note and the actual `src/matching/engine.py`/`claude_sonnet_client.py` source during this session. LOW reflects the missing Verification Record trail, not uncertainty about the text itself.

## 3. INTEGRATION_CONTRACTS.md Impact
Status: AFFECTED

### Azure Event Grid (auto-intake webhook) — IP-010
Change Type: ADDED
| Field | Before State | After State | Operational Notes |
|---|---|---|---|
| What application sends | N/A — no entry existed | Documented as an inbound trigger; on a valid, authorized delivery, M-046 calls M-039 to download the PDF, then queues it as a job (M-045 batch grouping) | Entry was missing entirely despite TOPOLOGY.md's A03 already having recorded IP-010 since 2026-07-25 — a real cross-artifact completeness gap (P1-S3-006, see Section 6) |
| What application expects to receive | N/A | Event Grid `SubscriptionValidationEvent`, or a batch of `Microsoft.Storage.BlobCreated` events | |
| Auth mechanism | N/A | Shared secret (`VIVE_EVENTGRID_WEBHOOK_SECRET`), constant-time comparison; code-complete, not yet deployed (blocked on Azure RBAC) | |
| Error handling assumptions | N/A | Download hard-pinned to the configured dropzone container; 100-event cap per delivery | |
| Known divergences | N/A | None recorded — added in the same pass that documents it | |

### Claude Sonnet 4.6 (Anthropic, via Azure AI Foundry) — IP-001, Known Divergences bullets only
Change Type: MODIFIED
| Field | Before State | After State | Operational Notes |
|---|---|---|---|
| Known divergences — `line_confidence` bullet | Stated fabricated and unresolved ("see IC-15, RISK_REGISTER R-001") | Tagged `[RESOLVED — 2026-07-24]`; states the client now elicits and parses a genuine per-row confidence value | Matches the wording pattern used for the six related edits made earlier this session |
| Known divergences — totals-row bullet | Stated no exclusion existed, unresolved ("see RISK_REGISTER R-002") | Tagged `[RESOLVED — 2026-07-24]`; states `_is_totals_row()` now filters these rows | Same pattern |

Confidence: LOW
Notes: Directly sourced from the committed INTEGRATION_CONTRACTS.md text (both edits made and verified this session). LOW reflects the missing Verification Record trail underneath the substitute cross-reference, not the content itself.

## 4. INVARIANT_CATALOGUE.md Impact
Status: AFFECTED

### Existing Invariants — Changes Only
| Invariant ID | Change Type | Before State | After State |
|---|---|---|---|
| IC-15 | MODIFIED | "Currently enforced"/"Enforcing modules" fields listed M-023 among the providers still fabricating a flat 0.75 confidence, with no fix noted | Fields now state M-023 was fixed 2026-07-24 (genuine per-row confidence, see RISK_REGISTER R-001) and add M-023 to the enforcing-modules list; M-024/M-025/M-026 remain listed as broken |
| IC-20 | MODIFIED | "Currently enforced"/"Enforcement point"/"Enforcing modules" fields listed M-023 among clients with no totals-row filter | Fields now state M-023 received the filter 2026-07-24 (`_is_totals_row()`, see RISK_REGISTER R-002) and add M-023 to the enforcement-point/enforcing-modules fields; M-025/M-026 remain listed as unfiltered |

Operational Notes: Both corrections were made to keep each invariant internally consistent — e.g. IC-15's "Enforcing modules" line would otherwise directly contradict its own updated "Currently enforced" sentence naming M-023 as now genuinely protective.

### New Invariants Discovered During This Enhancement
None this pass. (IC-21 — the `VIVE_MAX_CONCURRENT_AI_CALLS` cap — was added during the prior 2026-07-25 scoped refresh, not during this correction window; not re-listed here to avoid conflating the two passes.)

Confidence: LOW per invariant
Notes: Directly sourced from the committed INVARIANT_CATALOGUE.md text (both edits made this session, cross-checked against RISK_REGISTER.md R-001/R-002's fix notes). LOW reflects the missing Verification Record trail, not doubt about the text itself.

## 5. RISK_REGISTER.md Impact
Status: AFFECTED

### Risks Introduced This Session
| Proposed ID | Description | Severity | Affected Module/Artifact |
|---|---|---|---|
| R-011 | `friendly_dt()` (`web/deps.py`) hardcodes IST for all displayed timestamps | High | M-010 |

Mitigation: None yet — tracked, not fixed. See Recommended Action in R-011's own entry (make the display timezone configurable via `VIVE_DISPLAY_TIMEZONE`).

Note on scope precision: R-009 and R-010 were **not** newly introduced this session — both were added during the prior 2026-07-25 scoped refresh. They are included below because this session's work directly touched them, not because they were newly created.

### Existing Risks — Confirmed / Referenced This Session
| Risk ID | Confirmation Note |
|---|---|
| R-009 | Not modified this session. Referenced from the RISK_REGISTER.md closing provenance line, which was updated to cross-reference the 2026-07-27 second pass (P1-S3-006/007/008) and R-011. |
| R-010 | Not modified this session. Its invariant (IC-21) gained a `THREATENS: R-010 → IC-21` edge during tonight's SYSTEM_GRAPH.json rebuild (Section 8). |

### Existing Risks — Severity Changed
None this session.

Confidence: LOW
Notes: Directly sourced from the committed RISK_REGISTER.md text and this session's own edits (R-011's addition, the closing provenance line update). LOW reflects the missing Verification Record trail underneath the substitute cross-reference, not the content itself.

## 6. ANNOTATION_CHECKLIST.md Impact
Status: AFFECTED

### New Items Surfaced During This Enhancement
| Proposed ID | Type | Description | Severity |
|---|---|---|---|
| P1-S3-006 | CONTRADICTION | IP-010 registered in TOPOLOGY.md's A03 but entirely absent from INTEGRATION_CONTRACTS.md | P1 |
| P1-S3-007 | CONTRADICTION | RISK_REGISTER R-001's Claude Sonnet confidence-fix note never propagated to `docs/INVARIANTS.md` INV-01, `docs/ARCHITECTURE.md` §8, INVARIANT_CATALOGUE IC-15, or MODULE_CONTRACTS finding #1 | P1 |
| P1-S3-008 | CONTRADICTION | RISK_REGISTER R-002's Claude Sonnet totals-row-fix note never propagated to INVARIANT_CATALOGUE IC-20 | P1 |
| P2-S3-003 | OPEN_QUESTION | MODULE_CONTRACTS cross-cutting finding #8 (`friendly_dt()` IST hardcoding) flagged for engineer confirmation at the original extraction and never followed up | P2 |

Type: CONTRADICTION | OPEN_QUESTION (per template vocabulary)

### Existing Items — Resolved During This Enhancement
| Item ID | Resolution | Evidence Source |
|---|---|---|
| P1-S3-006 | RESOLVED — IP-010 entry added to INTEGRATION_CONTRACTS.md | BUILD_OBSERVATION |
| P1-S3-007 | RESOLVED — all four locations corrected | BUILD_OBSERVATION |
| P1-S3-008 | RESOLVED — IC-20 corrected | BUILD_OBSERVATION |
| P2-S3-003 | PARTIALLY_RESOLVED — R-011 added to RISK_REGISTER.md; underlying `friendly_dt()` code defect remains open, not fixed | BUILD_OBSERVATION |

Evidence Source: BUILD_OBSERVATION (no `sessions/` Verification Records exist to cite instead)

Confidence: LOW
Notes: This section describes the full 2026-07-27 Stage 3 second pass appended to ANNOTATION_CHECKLIST.md this session, sourced directly from that committed text. LOW reflects the missing Verification Record trail underneath the substitute cross-reference, not the content itself.

## 7. DOMAIN_MODEL.json Impact
Status: NOT AFFECTED

`discovery/DOMAIN_MODEL.json` was not touched during this session — no entity, attribute, vocabulary, or relationship changes. Confirmed via `git status` (file not listed as modified).

## 8. SYSTEM_GRAPH.json Impact (supplementary — not one of the seven core BCE artifacts, included per explicit instruction)
Status: AFFECTED — full rebuild per `bce_core.md` Section 11.8

| Metric | Before | After |
|---|---|---|
| Total nodes | 86 | 90 |
| Total edges | 193 | 203 |
| Invariant nodes | 20 | 21 (IC-21 added) |
| RiskItem nodes | 8 | 11 (R-009/R-010/R-011 added) |
| OWNS edges | 20 | 21 (M-047→IC-21) |
| ENFORCES edges | 30 | 34 (M-047→IC-21, M-023→IC-21, M-023→IC-15, M-023→IC-20) |
| AFFECTS edges | 18 | 22 (R-009→M-046, R-009→M-039, R-010→M-047, R-011→M-010) |
| THREATENS edges | 6 | 7 (R-010→IC-21) |

Operational Notes: IC-19's node `statement` text was also corrected during the rebuild — it still read "system-wide," predating the 2026-07-24 per-`pdf_filename` amendment. IP-001's `CAN_VIOLATE` edges to IC-15/IC-20 were deliberately left unchanged — whether a now-resolved divergence should still emit a capability edge is ambiguous under the stated mechanical derivation rule, and this was flagged rather than decided unilaterally. Validated post-rebuild: zero duplicate node IDs, zero dangling non-cross-graph edge references (script-verified).

Confidence: LOW
Notes: The node/edge counts themselves were produced by a Python script parsing the actual before/after JSON (the most directly verifiable content in this entire file). Confidence is still marked LOW per instruction, consistent with every other section — the rating reflects that this whole BCE_IMPACT log rests on the substitute brief-vs-built cross-reference in place of a formal Verification Record trail, not any doubt about the specific counts, which are exact.

---

## Engineer Sign-Off
[x] I confirm this impact log is accurate.

**Scope note:** This wasn't a deliberate call — I was moving fast through a list
of build steps and didn't stop to check each one against the original brief as
I went.

**friendly_dt() / IST timestamp bug:** Nothing further to add — this wasn't
something I was aware of until it was flagged tonight.

**Signed:** Ayush Kumar Sinha
**Date:** 2026-07-27