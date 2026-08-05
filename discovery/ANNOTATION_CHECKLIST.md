# ANNOTATION_CHECKLIST.md — VIVE Reconciliation

This is the BCE backlog — items surfaced during extraction that require an engineer decision, annotation, or judgment call before they can be considered resolved. Opened during Session F03 (Domain Model Synthesis) this pass, ahead of the formal Stage 3 cross-artifact review that will run after Sessions B/C/G/U complete. Per methodology, this file is never empty on a real system — new items accumulate here as extraction proceeds.

---

### P2-F03-001 · `silver_reconciliation_standard.statement_date` does not store a date ([DOMAIN_MODEL.json A-006])

**Severity:** P2
**Type:** OPEN_QUESTION
**Source:** CODE_EXTRACTION
**Surfaced by:** CC (Session F03, while extracting the `statement_date` attribute)
**Artifact:** `DOMAIN_MODEL.json` (A-006)
**Section:** Attribute A-006

**Observation:** `notebooks/01_document_intake.py`'s `normalize_to_silver()` writes `row.get("statement_period")` into the `statement_date` column, with its own inline comment confirming this is deliberate: `"# statement_date — use period as proxy"`. A column named for a specific date (e.g. the date printed on the statement) actually holds a `YYYY-MM` period string throughout the VENDOR_STATEMENT side of this table.

**Risk for planning:** Any future engineer, report, or AI-planning pass that reads `statement_date` expecting a real date (for aging calculations, date-range filtering, or display) will get a period string instead. This is exactly the class of naming-vs-content mismatch BCE annotation exists to catch before it causes a real bug — e.g., a future "statements older than N days" feature built directly against this column would silently misbehave.

**Recommended action:** Engineer decides: (a) rename the column to something accurate (e.g. `statement_period_proxy` or simply drop it in favor of `statement_period`, which already exists as its own column on this same table and holds the real value) in a future migration, or (b) confirm this is intentional and acceptable as-is, with the business meaning recorded here for future readers rather than fixed.

**Engineer action required:** A naming/schema decision, or an explicit acceptance with rationale.

**STATUS:** OPEN — not yet reviewed by the engineer.

---

## Stage 3 — Cross-Artifact Review, 2026-08-05
Produced by: BCE Stage 3 (CC, per Path A precedent — human review gate is the enforcement mechanism)

All six BCE artifacts read in full before this review: `INTAKE_SUMMARY.md`, `TOPOLOGY.md`, `MODULE_CONTRACTS.md`, `INTEGRATION_CONTRACTS.md`, `INVARIANT_CATALOGUE.md`, `RISK_REGISTER.md`, plus `docs/INVARIANTS.md` and `docs/ARCHITECTURE.md` for cross-checking, per this session's earlier reads.

### CHECK 0 — Schema Validation Gate

Verified directly via grep (not assumed):
- `A02_module_call_map.md` Module Roster: all 50 modules M-001–M-050 assigned, sequential, no gaps.
- `A02_module_call_map.md` Internal Call Table: all edges use `M-NNN --[CALLS]--> M-NNN` or `M-NNN --[CALLS]--> IP-NNN` format.
- `TOPOLOGY.md` A03: all 11 external system records carry an `IP-NNN` field (confirmed count via grep).
- `MODULE_CONTRACTS.md`/component files: all `Callers`/`Calls`/`Integration Points Used` fields reference `M-NNN` or `IP-NNN` — one legitimate, deliberate exception: `B15_intake_trigger_router.md`'s `Callers` field reads `IP-010` rather than an `M-NNN`, correctly, since the actual caller is the external Event Grid system, not another internal module.
- `INVARIANT_CATALOGUE.md`: all `Owning module`/`Enforcing modules` fields reference `M-NNN` or the literal `none`.
- `INTEGRATION_CONTRACTS.md`: all 11 records begin with `IP-NNN`; all `Called by` fields reference `M-NNN`.
- `RISK_REGISTER.md`: all `Affected modules` fields reference `M-NNN`; all `Threatened invariant` fields reference `IC-N` or the literal `None formal`.
- `DOMAIN_MODEL.json`: all node IDs correctly formatted (`E-001`; `A-001`–`A-026`; `SV-001`; `SVV-001`–`SVV-002`). No `REL-NNN` entries — correctly absent (single-entity canonical boundary, zero relationships to name), not a violation.
- `SYSTEM_GRAPH.json` does not exist yet — correctly deferred until after this gate passes.

**Zero SCHEMA_VIOLATION items produced. Schema validation PASS — proceeding to Check 1.**

---

### CHECK 1 — Cross-Artifact Contradiction Detection

- **TOPOLOGY.md vs MODULE_CONTRACTS.md** (module names, call relationships, layer assignments): Verified matching — same 50 module names, same M-NNN, same layer assignments (15 serving / 21 pipeline / 14 infra) in both, since MODULE_CONTRACTS.md's index was built directly from A02's roster this session. No contradiction.
- **TOPOLOGY.md vs INTEGRATION_CONTRACTS.md** (external system names, boundary descriptions): Same 11 `IP-NNN` records in both (INTEGRATION_CONTRACTS.md was synthesized directly from TOPOLOGY.md's A03 this session). No contradiction.
- **MODULE_CONTRACTS.md vs INVARIANT_CATALOGUE.md** (enforcement points, module sources): Spot-checked IC-15/IC-19 (the two Fabric-related entries) against `G01_lakehouse_connection.md`'s Known Fragility — both describe the same facts consistently (PARTIAL enforcement, M-003/M-017 as the actual write sites). No contradiction found.
- **INVARIANT_CATALOGUE.md vs docs/INVARIANTS.md** (invariant statements, coverage): **One real contradiction found.** `docs/INVARIANTS.md`'s INV-06 states `Scope: GLOBAL` outright. `INVARIANT_CATALOGUE.md`'s IC-06 (same invariant) reclassifies it as `TASK-SCOPED`, with reasoning given inline — but `docs/INVARIANTS.md` was not updated to match. → **CON-001**. Separately, **a coverage gap, not a contradiction**: 12 of `INVARIANT_CATALOGUE.md`'s 19 entries (IC-08 through IC-19) have no representation in `docs/INVARIANTS.md` at all — most were sourced from `RULES.md` or code observation, never promoted to the formal invariants document. IC-08 (RULE-01's normalization restraint) is the clearest promotion candidate, already flagged in its own entry.
- **RISK_REGISTER.md vs MODULE_CONTRACTS.md** (Known Fragility fields vs risk entries): Cross-checked all 50 component files' Known Fragility sections against the 13 risk entries. All fragilities with genuine operational/security/data-integrity weight are covered. Two fragilities were considered and deliberately **not** promoted to a risk entry, recorded here so they aren't silently lost: `C09_document_understanding_engine.md`'s dead `VISION_PROMPT` code (a wasted-effort/tech-debt finding, not an active risk) and `B12_upload_router.md`'s silent partial-batch-upload-failure (no per-file error isolation) — the latter is closer to risk-register-worthy than the former; flagged below as **P3-S3-005** for the engineer's own judgment rather than added unilaterally.

---

### CHECK 2 — NOT DETERMINABLE Escalation

Searched all five living Stage 2 artifacts directly for `NOT DETERMINABLE`. Found exactly 2 instances, both in `INVARIANT_CATALOGUE.md`'s CQ-001 entry (`Currently enforced` and `Enforcement point` fields) — both legitimately not determinable from source, since CQ-001 is a human code-review discipline with no linter/static-analysis backing found in this codebase. **Informational only (P3) — not an extraction gap.** No checklist item required beyond noting it here.

---

### CHECK 3 — Stage-2-Divergence Resolution Status

One genuine `[STAGE-2-DIVERGENCE — 2026-08-05]` finding exists this pass (the Fabric cut-over scope/RULE-13 staleness, documented in `TOPOLOGY.md` and `INVARIANT_CATALOGUE.md` IC-15). **Not yet resolved by the engineer.** Per methodology, unresolved STAGE-2-DIVERGENCE items default to P1. → **P1-S3-002**.

---

### CHECK 4 — Missing Invariant Candidates

Compared every `MODULE_CONTRACTS.md` Known Fragility/Change Impact field against `INVARIANT_CATALOGUE.md`'s 19 entries. Every fragility that represents a genuine "must always hold" constraint already has a corresponding IC-N entry (IC-08 for RULE-01's restraint, IC-18 for route-registration order, IC-19 for the Fabric concurrency gap). **No new invariant candidates found — check is clean.**

---

### CHECK 5 — Risk Register Severity Review

Reviewed all 13 `RISK_REGISTER.md` entries against their cited fragility/invariant impact. Twelve are internally consistent (severity matches description and blast radius, downgrades/upgrades from the archived record are justified with evidence). **One presentation inconsistency found:** R-009 uses `"Fixed in code / deployment pending"` as its severity field — not one of the standard severity levels (Critical/High/Medium/Low) used everywhere else in the register, overloading a status concept into the severity field. → **P3-S3-004**.

---

### CHECK 6 — Cross-Artifact Consistency Check
**Last run:** 2026-08-05 **By:** CC (per Path A precedent)

| Check | Status | Notes |
|---|---|---|
| All invariants in INVARIANT_CATALOGUE.md match INVARIANTS.md | FAIL | INV-06/IC-06 scope contradiction (CON-001); 12 IC entries absent from INVARIANTS.md entirely (coverage gap, not itself a failure of this check but recorded here for visibility) |
| All module names in MODULE_CONTRACTS.md match TOPOLOGY.md | PASS | Verified directly — same 50 names, same M-NNN, same layers |
| All external systems in INTEGRATION_CONTRACTS.md match TOPOLOGY.md A03 | PASS | Same 11 IP-NNN records, same names, in both |
| All risks in RISK_REGISTER.md reference correct source artifacts | PASS | All 13 entries correctly cite IC-N or `None formal`, and M-NNN throughout |
| INTAKE_SUMMARY.md open questions accounted for in artifacts | PASS | All 5 open questions from `INTAKE_SUMMARY.md` (the 3 new `.docx` files, INV-06 classification, IC-19/INV-05 re-confirmation, Fabric migration scope, PROJECT_MANIFEST/REGISTRY sign-off) are addressed or explicitly tracked across TOPOLOGY.md, INVARIANT_CATALOGUE.md, and RISK_REGISTER.md — the `.docx` files remain genuinely unread, tracked as an open item, not silently dropped |
| Entity names in DOMAIN_MODEL.json consistent with domain terminology in INVARIANT_CATALOGUE.md and MODULE_CONTRACTS.md | PASS | "Invoice" (E-001) used consistently; `silver_reconciliation_standard` referenced identically across all artifacts |

---

## New Checklist Items — Stage 3, 2026-08-05

### P1-S3-001 · INV-06/IC-06 GLOBAL vs. TASK-SCOPED contradiction between docs/INVARIANTS.md and INVARIANT_CATALOGUE.md
**Severity:** P1
**Type:** CONTRADICTION
**Source:** CODE_EXTRACTION
**Surfaced by:** CC
**Artifact:** `docs/INVARIANTS.md` (INV-06); `INVARIANT_CATALOGUE.md` (IC-06)
**Section:** INV-06; IC-06
**Observation:** `docs/INVARIANTS.md` declares INV-06 (AI-call concurrency cap) `Scope: GLOBAL` with no hedge. This session's `INVARIANT_CATALOGUE.md` reclassifies the same invariant as `TASK-SCOPED`, reasoning that no task outside `src/ai/`/`web/worker.py` plausibly interacts with AI-call concurrency, and that its category (Structural/resource-governance) differs from IC-01–05's (Domain/financial-integrity). This resolves an ambiguity that was left open earlier in this engagement (`docs/Claude.md` §2's own footnote hedges rather than resolving it) — but the resolution exists only in the fresh catalogue, not yet reflected back into `docs/INVARIANTS.md` or `Claude.md`.
**Risk for planning:** A future build session reading `docs/INVARIANTS.md`/`Claude.md` directly (the frozen execution contract) would still see INV-06 as GLOBAL, while a session consulting the BCE catalogue would see TASK-SCOPED — two authoritative-looking sources disagreeing.
**Recommended action:** Engineer decides whether to accept the TASK-SCOPED reclassification (in which case `docs/INVARIANTS.md`'s INV-06 scope field and `Claude.md`'s §2 footnote need updating via the amendment prompt) or explicitly reject it and keep GLOBAL (in which case `INVARIANT_CATALOGUE.md`'s IC-06 needs reverting).
**Engineer action required:** A scope classification decision, applied consistently across both documents.
**Engineer decision (2026-08-05):** Accept the TASK-SCOPED reclassification in principle — `docs/INVARIANTS.md` and `Claude.md` §2 will be edited in a later pass, not this session. The contradiction between the two documents is consciously deferred, not silently left unresolved: `INVARIANT_CATALOGUE.md`'s IC-06 is the currently-intended target state; `docs/INVARIANTS.md`'s INV-06 remains GLOBAL in the frozen execution contract until that later edit lands.
**STATUS:** SIGNED-OFF — deferred, with rationale recorded. Follow-up: update `docs/INVARIANTS.md` INV-06 scope field and `Claude.md` §2's footnote to TASK-SCOPED in a future pass.

---

### P1-S3-002 · Fabric cut-over scope/RULE-13 staleness STAGE-2-DIVERGENCE unresolved
**Severity:** P1 (per unresolved-STAGE-2-DIVERGENCE default)
**Type:** OPEN_QUESTION
**Source:** CODE_EXTRACTION
**Surfaced by:** CC
**Artifact:** `TOPOLOGY.md` (A01 row 8); `INVARIANT_CATALOGUE.md` (IC-15); `RISK_REGISTER.md` (R-012)
**Section:** As listed
**Observation:** The Fabric Warehouse cut-over's actual 3-table scope, and the resulting partial break in `RULES.md` RULE-13's backend-agnosticism promise, is documented as a divergence in three places this session but has not been resolved by the engineer — see `TOPOLOGY.md`'s Stage 2 Completeness Summary for the full cross-reference.
**Risk for planning:** Any enhancement touching the storage layer (including the planned broader Fabric migration) is planning against a RULE-13 description that no longer matches reality for 3 of the system's tables.
**Recommended action:** Confirm whether `RULES.md` RULE-13 should be updated to describe the Fabric path as a documented, scoped exception, and whether IC-19 should be promoted into `docs/INVARIANTS.md` given it currently does NOT hold.
**Engineer action required:** A documentation-update decision plus confirmation of IC-19's promotion status.
**Engineer decision (2026-08-05):** Update `RULES.md` RULE-13 to describe the Fabric path as a documented, scoped exception (done — see RULE-13's new "Scoped exception — Fabric Warehouse cut-over" paragraph, cross-referencing R-012/IC-19/TOPOLOGY.md A01 row 8). IC-19 stays BCE-catalogue-only for now — not promoted into `docs/INVARIANTS.md` — tracked instead via `RISK_REGISTER.md` R-012 as an accepted, mitigation-pending risk.
**STATUS:** RESOLVED — RULE-13 updated 2026-08-05.

---

### P2-S3-003 · docs/INVARIANTS.md coverage gap — 12 of 19 catalogued invariants absent
**Severity:** P2
**Type:** OPEN_QUESTION
**Source:** STAGE3_REVIEW
**Surfaced by:** CC
**Artifact:** `docs/INVARIANTS.md`; `INVARIANT_CATALOGUE.md` (IC-08 through IC-19)
**Section:** Whole-document comparison
**Observation:** `docs/INVARIANTS.md` (the formal, Claude.md-feeding document) contains only INV-01–06 + CQ-001. `INVARIANT_CATALOGUE.md`'s IC-08 through IC-19 — sourced from `RULES.md`'s 13 rules, `Claude.md` §5's Rules 3–5, and 2 new code-observed findings — have no representation there at all.
**Risk for planning:** A build session that reads only `docs/INVARIANTS.md`/`Claude.md` (its actual, frozen execution contract) never sees these 12 constraints formally, even though several (IC-08 especially) are historically significant, reverted-when-violated invariants.
**Recommended action:** Engineer selects which of IC-08–IC-19 warrant formal promotion into `docs/INVARIANTS.md` (IC-08 is the strongest candidate) versus which are fine remaining BCE-only documentation.
**Engineer action required:** A promotion-triage decision across 12 candidate invariants.
**STATUS:** OPEN — not yet reviewed by the engineer.

---

### P3-S3-004 · RISK_REGISTER.md R-009's severity field overloads status and severity
**Severity:** P3
**Type:** OPEN_QUESTION
**Source:** STAGE3_REVIEW
**Surfaced by:** CC
**Artifact:** `RISK_REGISTER.md` (R-009)
**Section:** R-009
**Observation:** R-009 uses `"Fixed in code / deployment pending"` in its Severity field, rather than a standard severity level — every other entry in the register uses Critical/High/Medium/Low. This makes the summary table's Severity column inconsistent for programmatic/at-a-glance scanning.
**Risk for planning:** Low — cosmetic/consistency only, no material risk understated or overstated.
**Recommended action:** Consider giving R-009 both a standard severity level (its severity if the deployment gap were never closed — likely High, matching its pre-fix rating) and a separate Status field, rather than conflating the two.
**Engineer action required:** Approve the cosmetic restructuring, or accept as-is.
**STATUS:** OPEN — not yet reviewed by the engineer.

---

### P3-S3-005 · Two Known Fragility findings considered for RISK_REGISTER promotion, not added
**Severity:** P3
**Type:** OPEN_QUESTION
**Source:** STAGE3_REVIEW
**Surfaced by:** CC
**Artifact:** `MODULE_CONTRACTS.md` (via `C09_document_understanding_engine.md`, `B12_upload_router.md`)
**Section:** Known Fragility fields
**Observation:** (1) `VISION_PROMPT` (M-024) is confirmed dead code for the active provider — a tech-debt/clarity finding, not an active risk. (2) `web/routers/upload.py` (M-012) has no per-file error isolation in its upload loop — a partial batch failure could silently leave some files queued and others not, with no indication to the user of which succeeded. The second is closer to risk-register-worthy than the first.
**Risk for planning:** Low for (1); Medium-plausible for (2) if batch uploads are common and failure-prone in practice.
**Recommended action:** Engineer's call on whether (2) warrants a formal R-014 entry; (1) is likely fine as a MODULE_CONTRACTS.md-only note.
**Engineer action required:** A promotion decision on item (2) specifically.
**STATUS:** OPEN — not yet reviewed by the engineer.

---

## Stage 3 Completeness Summary — 2026-08-05
Produced by: BCE Stage 3 (CC, per Path A precedent)

P1 items: 2 (P1-S3-001, P1-S3-002) — must be SIGNED-OFF or RESOLVED before Stage 3 completes
P2 items: 2 (P2-F03-001 carried from Session F, P2-S3-003) — tracked, resolve before first enhancement
P3 items: 2 (P3-S3-004, P3-S3-005) — informational backlog
CON items: 1 (folded into P1-S3-001 above, not double-counted)
Total items this pass: 5 new + 1 carried forward = 6

Consistency check: FAIL at time of check — 1 failure (INV-06/IC-06 scope mismatch) — dispositioned below, same day.

**Both P1 items dispositioned 2026-08-05:** P1-S3-001 SIGNED-OFF (deferred, with rationale — `docs/INVARIANTS.md`/`Claude.md` to be edited in a later pass). P1-S3-002 RESOLVED (`RULES.md` RULE-13 updated same day).

**Stage 3 is complete.** Both P1 items carry a direct engineer decision, recorded above. Engineer sign-off: confirmed in conversation, 2026-08-05. Proceeding to the mandatory Stage 3 close-out step — Graph Construction (`discovery/SYSTEM_GRAPH.json`).
