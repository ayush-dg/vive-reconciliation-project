# ENH-001_BCE_IMPACT.md

## Header
Enhancement: ENH-001 — UI clarity fixes + multiple PDF upload
Engineer: Vaishali
Phase 8 sign-off date: 06-09-2026
BCE close-out date: 06-09-2026
Sprint: SPRINT-001

## BCE Gap Detection
Status: CLEAN

Two passes run (general-purpose agent, fresh context each time). First pass found gaps
clustered around Task 2.1 (its crash-recovery fix quietly closed part of what
IC-CANDIDATE-01/R-005 describe, without updating either), Task 2.2 (a new module and a
narrowed module-contract characterization), Task 1.4 (an unpromoted risk), and the two
post-sign-off hotfixes (H1/H2 — real module-contract-level changes with no BCE Impact
trail at all, since they bypassed the per-task PBVI cycle). All gaps were resolved by
adding BCE Impact rows to the relevant Verification Record or Session Log (not by editing
`discovery/` directly — deferred to sprint close-out per doctrine). Second pass confirmed
all six artifact tables empty.

| BCE Artifact | Gaps found (pass 1) | Status after resolution |
|---|---|---|
| TOPOLOGY.md | 2 (Task 2.1 A01 failure mode; Task 2.2 A02 roster count) | CLOSED |
| MODULE_CONTRACTS.md | 6 (Task 2.1 M-046 ×2; Task 2.2 M-070, new module; H1 M-028; H2 M-076) | CLOSED |
| INTEGRATION_CONTRACTS.md | 0 | CLEAN (no gaps either pass) |
| INVARIANT_CATALOGUE.md | 2 (Task 2.1 IC-CANDIDATE-01; H1 G3 line citations) | CLOSED |
| RISK_REGISTER.md | 2 (Task 2.1 R-005; Task 1.4 unpromoted ICU risk) | CLOSED |
| ANNOTATION_CHECKLIST.md | 1 (Task 2.1 P2-S3-009 stale framing) | CLOSED |

## 1. TOPOLOGY.md Impact
Status: AFFECTED

### Layer Boundary Map
Status: AFFECTED
| Boundary | Change Type | Before State | After State | Operational Notes |
|---|---|---|---|---|
| A01 — M-046 crossing (`api/documents/[id]/extract/route.ts`) | MODIFIED | Documented failure modes: 404 (not found), 409 (already processing) | Adds a third failure mode: 422 (`{ok:false, reason:'recovery_exhausted'}`) when a document's Silver-recovery attempt is exhausted | Task 2.1. Confidence: HIGH — directly observed in `S2_VERIFICATION_RECORD.md` Task 2.1's own test evidence (TC-6). |

### Module Call Map
Status: AFFECTED
| Caller | Callee | Change Type | Before State | After State | Operational Notes |
|---|---|---|---|---|---|
| `UploadForm.tsx` (M-070) | `src/lib/batchUploadSequencing.ts` (new, unassigned) | ADDED | No such module existed; roster documented as "COMPLETE, 78 modules" | New pure-function module added, not yet in the roster — count and completeness claim both now stale | Task 2.2. Confidence: MEDIUM — the module's own contract fields (Inputs/Outputs/Error Behaviour/etc.) require the engineer's judgment to author correctly, not just a roster-count bump. **Operational note:** this module was deliberately extracted as a standalone pure function (not written inline in `UploadForm.tsx`) specifically so the "no two extractions in flight simultaneously" acceptance criterion could be genuinely unit-tested (`scripts/test_batch_upload_sequencing.sh`) — matching this codebase's own convention that every `test_*.sh` script tests `src/lib` directly, never React component internals. Worth preserving that rationale when the module gets its formal contract entry. |

### External System Boundary Map
Status: NOT AFFECTED

No external system's boundary contract changed. H1 changed the *content* of a system
prompt sent to an already-documented external system (IP-001/Claude) — see
`INTEGRATION_CONTRACTS.md Impact` below for why that's NOT AFFECTED at the contract
level despite being a real behavior change.

Confidence: HIGH
Notes: N/A

## 2. MODULE_CONTRACTS.md Impact
Status: AFFECTED

### M-022 (`extractionPipeline.ts`)
Change Type: MODIFIED
| Field | Before State | After State | Operational Notes |
|---|---|---|---|
| Known-fragility note | "No rollback of the `'processing'` status column if the pipeline throws" | Fixed — a `finally`-block-equivalent reset now returns status to `'registered'` on a recoverable Silver-normalization failure or an exhausted-recovery error | Task 2.1. Confidence: HIGH. |
| Outputs | No `SilverNormalizationFailure`/`RecoveryAttemptsExhausted` error types | Two new exported error classes; `runExtractionPipeline` takes a new optional `{skipSuccessGuard?: boolean}` parameter — existing call signature unaffected (default `false`) | Task 2.1. Confidence: HIGH. |

### M-015 (`extraction.ts`)
Change Type: MODIFIED
| Field | Before State | After State | Operational Notes |
|---|---|---|---|
| Cross-cutting findings claim | "Only the matching lock (M-047) recovers cleanly from a mid-run crash; the extraction lock (M-046) does not" | No longer accurate for an in-process JS exception (the residual gap is narrower — a true OS-level process crash/restart, out of scope, not a regression) | Task 2.1. Confidence: HIGH. |
| Outputs | `TriggerExtractionResult` had no recovery-related variant | New `'recovery_exhausted'` reason added; new `needsSilverRecovery()` helper (checks latest attempt passed AND zero Silver rows exist) drives when the recovery path is invoked | Task 2.1 (this helper wasn't in the original CC prompt — added because the prompt specified the recovery mechanism but not how a real trigger call decides to invoke it; engineer-directed scope addition, see Decision Log). Confidence: HIGH. |

### M-046 (`api/documents/[id]/extract/route.ts`)
Change Type: MODIFIED
| Field | Before State | After State | Operational Notes |
|---|---|---|---|
| Most notable finding | "Lock is non-releasing on failure... no finally/unlock path" | Fixed for the in-process-exception case (see M-015 above) — this route's underlying `triggerExtraction()` call now resets status on both a recoverable and an exhausted-recovery failure | Task 2.1. **Correction:** `S2_VERIFICATION_RECORD.md`'s own Task 2.1 BCE Impact section originally mislabeled this route as "M-044's sibling, not separately M-numbered" — it is in fact already-catalogued M-046. Corrected during Phase 8 gap detection. Confidence: HIGH. |
| Error Behaviour | 404, 409 | 404, 409, 422 (see TOPOLOGY.md A01 above) | Task 2.1. Confidence: HIGH. |

### M-070 (`UploadForm.tsx`)
Change Type: MODIFIED
| Field | Before State | After State | Operational Notes |
|---|---|---|---|
| Most notable finding | "Auto-chains a silent, un-awaited extraction call after upload" | Only true for a single-file upload now. A 2+-file batch explicitly *awaits* each file's full register+extract cycle before the next file's registration begins — a deliberate design choice (see Task 2.2's Design Note: "no two extractions in flight simultaneously") | Task 2.2. Confidence: HIGH. |
| Inputs | Single-file selection only | Multi-file selection (up to `MAX_BATCH_SIZE = 15`), rejected outright (not truncated) if exceeded | Task 2.2. Confidence: HIGH. |
| Outputs | Single per-file toast on success/failure; single "Uploaded statements" table row per file | Task 2.3 adds a live per-file `BatchRow` progress list (`queued`/`registering`/`extracting`/`done`/`failed`), gates the historical table's click-through behind a table-wide `batchInProgress` boolean while any multi-file batch is non-terminal. Task 2.4 adds a single running "X/N uploaded" toast for a real (>1 file) batch, replacing N individual per-file success toasts for that case only — single-file behavior unchanged. | Tasks 2.3/2.4. Confidence: HIGH. |
| Dependencies | — | New: `src/lib/batchUploadSequencing.ts` (Task 2.2, see TOPOLOGY.md above); calls existing `toastStore.add()`/`dismiss()` (M-009) directly for Task 2.4's counter — confirmed zero-diff on `toastStore.ts`/`ToastProvider.tsx` (M-009/M-083) via `git status` at commit time | Tasks 2.2/2.4. Confidence: HIGH. |

### M-076 (`DocumentDetailView.tsx`)
Change Type: MODIFIED
| Field | Before State | After State | Operational Notes |
|---|---|---|---|
| Outputs | Confidence/Provider columns removed from the extracted-lines table (Task 1.2); separate standalone "Extraction summary" panel showing per-provider counts | H2 (post-sign-off hotfix): standalone panel removed entirely; the same provider information is now folded into the existing `reconciliation-progress` sentence across all three of its states (no lines yet / not reconciled yet / complete) | H2. Confidence: HIGH — engineer-directed, fully tested (10/10 `document-detail.spec.ts`). **Operational note:** the first implementation pass gated the new phrase behind `totalLines > 0`, which would have silently dropped provider info for a genuinely FAILED extraction (zero Silver lines, but a provider WAS attempted) — exactly the case that matters most diagnostically. Caught and fixed before commit, not after — worth remembering if this module's display logic is touched again: "no lines" and "no provider was attempted" are different facts and must not be conflated. |

### M-028 (`aiProvider.ts`)
Change Type: MODIFIED
| Field | Before State | After State | Operational Notes |
|---|---|---|---|
| Most notable finding | max_tokens truncation fix (Task 8.2) | H1 (post-sign-off hotfix): `EXTRACTION_SYSTEM_PROMPT` now explicitly instructs the model to exclude non-transactional summary rows ("Previous Balance", "Balance Forward", "Opening Balance", "Beginning Balance") from extracted lines | H1. Confidence: MEDIUM. **Operational note (mandatory, per Confidence Rating Guide):** this fix was root-caused live against a real statement (Berlin City Auto Group) where such a row was extracted as a fake line item, failing both the structural gate (no invoice/RO number) and the arithmetic gate (the row's amount was double-counted, since the vendor's own stated total already reflected it). The fix is implemented and typechecks, but **its actual effect on the live-Claude path that motivated it was never confirmed** — the engineer's retry after the fix resolved via the known-vendor deterministic (pdfplumber) route instead of Claude, so this exact failure mode remains unexercised by live data. Do not treat this as a verified fix without a follow-up live-Claude test against a statement with a genuine balance-forward row. |

### New module: `src/lib/batchUploadSequencing.ts`
Change Type: ADDED
| Field | Before State | After State | Operational Notes |
|---|---|---|---|
| (no prior entry) | — | Pure function `runBatchUploadSequenced(files, registerFile, extractDocument)`. Single-file: fires extraction without awaiting (byte-for-byte pre-enhancement regression). Multi-file (2+): awaits each file's full register+extract cycle sequentially — "no two extractions in flight simultaneously." Treats an extraction failure the same as a registration failure (skip, continue); an anomalous ok/no-`documentId` result is a no-op skip. | Task 2.2. Confidence: MEDIUM — needs a formal M-NNN ID assignment and full contract table (Inputs/Outputs/Error Behaviour/Dependencies/Invariants Enforced), pending senior review per the New Invariants convention's spirit even though this is a module, not an invariant. **Operational note:** extracted as a standalone module specifically for direct unit-testability (`scripts/test_batch_upload_sequencing.sh`, 12/12), matching this codebase's established convention — the alternative (inline in `UploadForm.tsx`) would have made the sequencing guarantee only inferable from Playwright network waterfalls, weaker evidence. |

## 3. INTEGRATION_CONTRACTS.md Impact
Status: NOT AFFECTED

H1 changed the *content* of the fixed system-prompt string sent to IP-001 (Claude), but
not the structural mechanism the integration contract actually documents: auth, the
messages/tool-call request shape, error-handling assumptions, or the "fixed
`EXTRACTION_SYSTEM_PROMPT` constant, never built from document content" framing — all
unchanged and re-confirmed by the untouched G3 byte-identity test
(`test_prompt_injection_defense.mjs`). NOT AFFECTED is the correct positive statement
here, not an omission — confirmed independently by two BCE gap detection passes.

Confidence: HIGH
Notes: N/A

## 4. INVARIANT_CATALOGUE.md Impact
Status: AFFECTED

### Existing Invariants — Changes Only
| Invariant ID | Change Type | Before State | After State |
|---|---|---|---|
| IC-CANDIDATE-01 | MODIFIED | "Currently enforced: PARTIAL — YES for matching, NO for extraction," supported by "`src/lib/extraction.ts:36-49` sets `status='processing'` and never resets it on any failure path" | Task 2.1 directly contradicts this: `triggerExtraction()` now resets status to `'registered'` on both a recoverable `SilverNormalizationFailure` and an exhausted-recovery error. Residual gap is narrower (a true OS-level process crash, not a JS exception) than currently described. |
| G3 | MODIFIED (citation only, not mechanism) | Enforcement point cites `src/lib/aiProvider.ts:67-79,190-216` | H1's new instruction text almost certainly shifted these line ranges within `EXTRACTION_SYSTEM_PROMPT`. The structural-separation mechanism itself is unaffected (unchanged G3 test) — only the line citations need re-verification against current file content. |

Operational Notes: IC-CANDIDATE-01's verdict and Rationale text need rewriting to reflect
the narrowed residual gap, not just a status flip — a reader should come away
understanding exactly what's still unprotected (process crash/restart) versus what's now
fixed (in-process exceptions), since conflating the two would understate the real,
remaining exposure.

Confidence: MEDIUM for IC-CANDIDATE-01 (the exact updated Rationale wording is an
authoring judgment call, not a mechanical fact); HIGH for G3 (citation drift is a
mechanical fact, easily re-verified by reading the current file).

### New Invariants Discovered During Build
None.

## 5. RISK_REGISTER.md Impact
Status: AFFECTED

### Risks Resolved By This Enhancement
None fully resolved — see "Existing Risks — Severity Changed" below; R-005 is narrowed,
not closed.

### Risks Introduced By This Enhancement
| Proposed ID | Description | Severity | Affected Module/Artifact |
|---|---|---|---|
| (pending ID) | Deployment Node build may lack full ICU (`Asia/Kolkata` timezone data) — not verified against the actual Azure App Service runtime, only local/dev. IST display could silently degrade to UTC or throw. | MEDIUM (proposed — engineer to confirm) | M-068 (`HomeView.tsx`), M-070 (`UploadForm.tsx`) — `formatUploadTimestamp()` |
| Mitigation | Recommended Action |
|---|---|
| Verify the actual Azure App Service Node runtime's ICU data includes `Asia/Kolkata` (either via a deployed smoke check or by confirming the Node build includes full-icu) before relying on this display in production. | Add to backlog — not exercisable via a Playwright test against the local dev server, which always has full ICU. |

### Existing Risks — Severity Changed
| Risk ID | Previous Severity | New Severity | Reason |
|---|---|---|---|
| R-005 | (as previously catalogued) | Narrowed scope — proposed for engineer re-scoring | Description stated extraction's lock "has no equivalent [to matching's self-releasing lock]... Only direct DB intervention recovers it." Task 2.1 fixes the in-process-exception case; the residual risk is narrower — a true process crash/restart only, not a regression from this enhancement. Actual severity re-score left to engineer judgment (Confidence: MEDIUM — this task fixed the common case, but whether the residual case still warrants the same severity number is a judgment call, not a mechanical fact). |

### Existing Risks — Confirmed Unmitigated
None reviewed as part of this enhancement beyond R-005 above.

Confidence: MEDIUM overall (new risk's exact severity number and R-005's re-score both
need engineer confirmation)
Notes: see operational notes embedded in each table above.

## 6. ANNOTATION_CHECKLIST.md Impact
Status: AFFECTED

### Existing Items — Resolved During This Enhancement
None.

### Existing Items — Escalated During This Enhancement
| Item ID | Original Severity | New Severity | Reason for Escalation |
|---|---|---|---|
| P2-S3-009 | OPEN | OPEN (reframe, not a severity escalation) | This item's entire subject is IC-CANDIDATE-01's "Owning module" mislabeling. Task 2.1 changed IC-CANDIDATE-01's underlying facts (see INVARIANT_CATALOGUE.md Impact above), but the checklist item still frames its discussion around the pre-fix "NO for extraction" state. Resolve together with the IC-CANDIDATE-01 rewrite, not independently against now-stale facts — listed here under "Escalated" only because the template has no better-fitting bucket for "still open, but now referencing stale facts"; it is not a severity bump. |

### New Items Surfaced During This Enhancement
None beyond what's captured as risks/invariant changes above.

Confidence: HIGH — P2-S3-009's dependency on IC-CANDIDATE-01 is a direct textual fact,
not a judgment call.

## 7. DOMAIN_MODEL.json Impact
Status: NOT AFFECTED

No entities, attributes, vocabulary, or relationships changed — confirmed by construction
(no schema/migration touched anywhere in ENH-001, a MANDATORY constraint per
`ENH-001_BRIEF.md`'s Known Constraints, upheld throughout both sessions and both
post-sign-off hotfixes).

Confidence: HIGH
Notes: N/A

## Confidence Rating Guide

HIGH: Derived entirely from Verification Records and planning artifacts. No additional
engineer input needed beyond confirmation of accuracy.

MEDIUM: Best-effort derivation — CC is missing information only the building engineer
holds. An operational note is mandatory for every MEDIUM section. The note must
answer: what is CC uncertain about, and what is the correct state?

LOW: Structural placeholder — CC could not derive this from available inputs. The
engineer must supply the content from memory. A LOW section with no operational note
is incomplete, not conservative.

An impact log submitted for sign-off with MEDIUM or LOW sections and no operational
notes must be returned for completion before it is accepted.

## Engineer Sign-Off


Enhancement: ENH-001 — ui-clarity-multi-pdf-upload
Engineer:Vaishali
Phase 8 sign-off date: 06-09-2026
BCE close-out date:06-09-2026
Sprint: SPRINT-001

### BCE Gap Detection Gate
[x] All gap detection tables empty — no unrecorded BCE impacts remaining
[x] All Verification Record BCE Impact sections complete and accurate

### Impact Coverage Confirmation
[x] TOPOLOGY.md — reviewed, status recorded
[x] MODULE_CONTRACTS.md — reviewed, status recorded
[x] INTEGRATION_CONTRACTS.md — reviewed, status recorded
[x] INVARIANT_CATALOGUE.md — reviewed, status recorded
[x] RISK_REGISTER.md — reviewed, status recorded
[x] ANNOTATION_CHECKLIST.md — reviewed, status recorded
[x] DOMAIN_MODEL.json — reviewed, status recorded (or marked NOT APPLICABLE)

### Tacit Knowledge Capture
[x] For every MEDIUM confidence section: operational note present, answers what CC
    could not derive and what the correct state is
[x] For every LOW confidence section: engineer-supplied content present, not a
    structural placeholder
