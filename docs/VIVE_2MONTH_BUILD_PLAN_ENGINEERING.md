> **SUPERSEDED 2026-08-16.** The decision changed to a ground-up rebuild in a fresh repo, aligned to the target architecture, instead of enhancing this codebase. See `docs/VIVE_REBUILD_PLAN_TARGET_ARCHITECTURE.md`. Kept here for history, not active.

# VIVE Reconciliation — 2-Month Engineering Build Plan

**Prepared:** 2026-08-16
**Window:** 2026-08-17 → 2026-10-09 (8 weeks / 4 two-week sprints)
**Team:** Ayush Kumar Sinha + Vaishali Rao Yellur
**Companion doc:** `docs/VIVE_2MONTH_BUILD_PLAN.md` (business/client-facing version — same schedule, no implementation detail)

This is the technical build order behind that plan: actual touch points, dependency/collision reasoning, and the process gates this repo already runs (Prompt 1 touch-point research → Prompt 2 collision-surface analysis → Engineer Sign-Off, per `enhancements/REGISTRY.md` and the SPRINT-001/SPRINT-002 pattern). Nothing here skips those gates — this schedule tells you *when* to run them, not *whether*.

---

## 0. Baseline facts (confirm still true before Week 1)

- Test suite: 281 passed / 18 failed (18 are local-environment-only — Azure CLI auth + one Windows file-lock issue, not code defects) — `docs/Claude.md` v2.9
- Fabric migration: 3 of 7 Recon tables (`extraction_cache`, `document_intake_log`, `validation_document_review_queue`) already on a real SQL database in Fabric item. Still on the old Azure SQL / SQLite path: `jobs`, `exception_dispositions`, `users`, `ai_audit_log`, plus all of Bronze/Silver/Gold.
- Matching engine (`src/matching/engine.py`) is deterministic-only (INV-02) — Level 1 exact invoice-number match, Level 2 RO-number+amount match, else `EXCEPTION`. No ranked-candidate output exists today — this is genuinely new logic, not an extension of an existing candidate list.
- NetSuite integration today: `src/mock_erp/generator.py` (mock, statement-scoped) and `scripts/load_voucher_data.py` (real voucher exports, vendor-scoped, standing in for live NetSuite per-vendor). **Live NetSuite API access is now available** — this plan treats the live adapter as new build work, not a config flip.
- Known hardcoded credential: `web/routers/auth.py:21-23,37` — `FALLBACK_EMAIL`/`FALLBACK_PASSWORD` (`admin@vive.com` / `Vive@2026`), used whenever DB lookup fails. Flagged in the file's own docstring as temporary-but-real.
- `RULES.md` RULE-08: explicit decision that no Admin/Reviewer role split exists today ("everyone using the dashboard does the same job... per-user logins exist so `resolved_by`/`disposed_by` mean something real, not to gate access"). Any scope creep from "harden login" into "add role tiers" requires a RULE-08 amendment — same governance weight as an invariant change, not a silent code decision.
- `INV-02` (`docs/Claude.md` v2.8) permits a narrow Pass-3 AI exception, but was amended unilaterally while the Sprint Lead was on leave and is recorded as **provisional, not yet a joint sign-off**. ENH-009 is blocked in `enhancements/REGISTRY.md` on her review — do not schedule build work against it until that lands.

---

## 1. New work not yet in the enhancement registry

Three items in this plan don't have ENH stubs yet. Recommend creating them in `enhancements/backlog/` following the existing Draft-stub pattern (see ENH-002 through ENH-014) before Week 1 starts, so they go through the same Prompt 1 / Prompt 2 gates as everything else:

| Proposed ID | Title | Depends on |
|---|---|---|
| ENH-015 (proposed) | Live NetSuite Invoice Fetch | — |
| ENH-016 (proposed) | Force-Match: Ranked Candidate Suggestions | ENH-015 |
| ENH-017 (proposed) | NetSuite Write-Back | ENH-008 (Audit Ledger), ENH-015 |

Suggested collision flags to carry into their briefs:
- **ENH-015 ↔ ENH-004** (Fabric migration) — both touch how ERP-side data is stored/retrieved; confirm ENH-015 writes to whichever backend `src/lakehouse/connection.py` is routing INTERNAL_ERP rows to at build time.
- **ENH-016 ↔ ENH-002** — force-match dispositions should be designed against ENH-002's run/work-item shape from day one so they don't need rework once runs exist.
- **ENH-017 ↔ ENH-008** — write-back must log through the unified audit ledger, not a standalone table; sequence write-back after ENH-008 lands (already reflected in the schedule below).

---

## 2. Dependency graph (as currently recorded)

```
ENH-002 (Run Management) ──┬── ENH-003 (Statement Versioning)
                            ├── ENH-008 (Audit Ledger) ──── ENH-017 (Write-Back, proposed)
                            └── ENH-014 (Email Alerts, soft)

ENH-015 (Live Fetch, proposed) ── ENH-016 (Force-Match, proposed)

ENH-005 (Doc Registry) ──╳── ENH-006 (Validation Hardening)   [collision — sequence, don't parallelize]
ENH-002 ──╳── ENH-004 (Fabric Migration)                       [collision]
ENH-004 ──╳── ENH-008                                          [collision — ai_audit_log is in both]

ENH-009 (Pass 3 AI Matching) — BLOCKED on Sprint Lead review of INV-02, independent of all of the above
```

Team capacity is 2 engineers — per the registry's own note, collision-flagged pairs are kept in different weeks/sprints below rather than assumed safe to build concurrently.

---

## 3. Sprint-by-sprint plan

### Sprint 1, Week 1 (Aug 17–21) — Live data + Run Management kickoff

**Engineer A (owns ENH-002, continuing the SPRINT-002 pattern):**
- Prompt 1 on ENH-002: confirm exact touch points — where the `jobs` table's per-file grouping ends and a run boundary begins (new table vs. grouping column), interaction with INV-05 (per-filename `PROCESSING` guard must not change)
- Begin Run Manager build per the reusable-components model: `run_id`, `reconciliation_type`, `business_context` (Vive fields: legal_entity, accounting_period, vendor_scope, AP_cutoff live here, not as core columns), `source_scope`, `target_scope`, `run_status`, lifecycle (create → preview → validate scope → freeze inputs → start → track → complete/fail/cancel)

**Engineer B (owns ENH-015, proposed):**
- Write the ENH-015 brief (Prompt 1): confirm auth flow, endpoint(s), rate limits, and exactly which fields map to `silver_reconciliation_standard`'s INTERNAL_ERP shape
- Build the NetSuite adapter as a clean boundary — isolate auth/endpoint/record-shape entirely inside `src/mock_erp/` or a new `src/erp_adapters/netsuite/` module (do not let NetSuite-specific fields leak into `src/matching/engine.py` or the Silver schema — matches the reusable-components brief's adapter boundary)
- Land open/unmatched invoices into the SQL database, replacing the mock generator / voucher-file path for reconciliation runs going forward (leave both old paths in place, don't delete — same "don't drop the rollback" pattern as the Fabric migration in `docs/Claude.md` v2.9)
- Confirm existing Upload flow (`web/routers/upload.py`) reconciles cleanly against live-fetched data end to end

**Demo (Fri):** Upload → reconcile against live NetSuite data.

---

### Sprint 1, Week 2 (Aug 24–28) — Force-match ships

**Engineer B (owns ENH-016, proposed):**
- Extend `src/matching/engine.py`'s residual (unmatched) path: for each `EXCEPTION` row, retrieve a ranked candidate set from Silver INTERNAL_ERP — score by vendor match + amount proximity + invoice-number string similarity. Keep this deterministic (no AI) — this sits squarely inside Pass 1/2 territory per INV-02, not Pass 3
- New disposition action: `force_match` — writes to `exception_dispositions` (or wherever ENH-008 lands the unified ledger, if that's ready in time — otherwise write to the existing table and plan a migration once ENH-008 ships)
- UI: extend `web/templates/exceptions_review.html` / `review_queue_review.html` to show ranked candidates + confidence + a force-match action button
- **Constraint check:** confirm this doesn't touch INV-01 (confidence gate) or INV-04 (never-null Silver fields) — candidate ranking is a review aid, not an auto-approval path; `force_match` always requires a human action

**Engineer A:**
- Continue ENH-002 — run entity CRUD + status transitions, run history list view

**Demo (Fri) — headline milestone:** Reviewer opens an exception, sees ranked NetSuite candidates with confidence %, force-matches one.

---

### Sprint 2, Week 3 (Aug 31–Sep 4) — Run Management lands, access hardening

**Engineer A:**
- Finish ENH-002: wrap existing per-file job processing without changing it (per the brief's explicit "Out of Scope" — a run is a grouping *above* `jobs`, not a replacement for `web/worker.py`)
- Update `enhancements/REGISTRY.md`: ENH-002 → COMPLETE

**Engineer B (owns ENH-010):**
- Resolve the RULE-08 scope question **before writing code** — is this (a) remove `FALLBACK_EMAIL`/`FALLBACK_PASSWORD` + harden login/session, or (b) actual role tiers requiring a RULE-08 amendment? Confirm with Sprint Lead; record the decision in `RULES.md` if it changes, don't let it get decided implicitly by what gets coded
- Remove the hardcoded fallback in `web/routers/auth.py:21-23,37`; add session hardening (rate limiting on login attempts)

**Demo (Fri):** Every reviewer has a real login; hardcoded credential gone; runs have their own dashboard/history.

---

### Sprint 2, Week 4 (Sep 7–11) — Statement versioning + orchestration

**Engineer A (owns ENH-003, now unblocked by ENH-002):**
- Define what a "work item" is precisely (per-file vs. per-invoice-line — brief flags this as still open)
- Must interact correctly with the extraction-cache-hit logic in `notebooks/01_document_intake.py`'s `check_cache()` — a reprocessed statement must never be silently treated as a cache hit if the underlying document actually changed
- New version anchors to the run that produced it

**Engineer B (owns ENH-011, per SPRINT-002_GUIDE.md's "build after ENH-002's schema stabilizes" note):**
- Wrap `scripts/run_full_pipeline.py` and the job queue with n8n scheduling/retry/alerting from *outside* — do not reimplement pipeline logic inside n8n
- Respect RULE-05 (mock ERP generator stays CLI-only, never gets an n8n-triggered HTTP path) and INV-05 (retry policy must not double-queue a job already `PROCESSING` for its filename)

**Demo (Fri):** Scheduled run executes unattended; reprocessed statement keeps lineage instead of creating a duplicate.

---

### Sprint 3, Week 5 (Sep 14–18) — Audit ledger + document registry

**Engineer A (owns ENH-008, now unblocked by ENH-002):**
- Confirm at Prompt 1 exactly which two logs are being unified — brief flags `ai_audit_log` and the `exception_dispositions` trail as candidates, not yet confirmed against live code
- Build as a generic, append-only decision ledger per the reusable-components model: `run_id`, `work_item_id`, `source_record_id`, `target_candidate_ids`, `evidence`, `rules_evaluated`, `AI_invoked`/`AI_result` (kept generic — no `NetSuiteInvoiceNumber`-style fields as first-class columns), `human_decision`, `final_disposition`, `decision_version`, `supersedes_decision_id`
- Reprocessing produces a new decision/version — never overwrite

**Engineer B (owns ENH-005):**
- Confirm whether this extends `document_intake_log` (already migrated to a real SQL database in Fabric item) or introduces a new table — any schema change goes through a new numbered migration file, never hand-edited DDL
- Full status vocabulary: received → checked → done (exact states TBD at Prompt 1)

**Demo (Fri):** Any match/force-match traces to a single ledger entry; any uploaded document shows full lifecycle status.

---

### Sprint 3, Week 6 (Sep 21–25) — Validation hardening + notifications

**Engineer B (owns ENH-006, sequenced after ENH-005 per the flagged collision on `document_intake_log`/intake validation gate):**
- Extend `notebooks/01_document_intake.py`'s `validate_invoice()` + `config/validation/extraction_rules.json` with an invoice-numbers-sum-to-statement-total check, plus other data-quality checks
- Must not weaken INV-01/INV-03/INV-04 — new checks are additive; any failing row routes to human review, never silently drops (same pattern already established for OCR-derived rows)

**Engineer A (owns ENH-014, scope confirmed against ENH-002's run boundary rather than the older `batch_id`):**
- Batch/run finish-or-fail emails — provider decision made here, not assumed in advance

**Demo (Fri):** Bad statement total flagged automatically; email fires on run completion/failure.

---

### Sprint 4, Week 7 (Sep 28–Oct 2) — Write-back + reporting

**Engineer A (owns ENH-017, proposed — depends on ENH-008 landing in Week 5):**
- Write-back adapter lives beside the ENH-015 fetch adapter — same boundary discipline (NetSuite specifics isolated, not leaked into the ledger or matching engine)
- **Guardrails, non-negotiable for this item:** test against a NetSuite sandbox/test account before any production write; every write requires explicit reviewer approval — never an automatic sync on every match; every write logged to the unified audit ledger (ENH-008) *before* it's considered final, so a failed/partial write is always traceable
- This is a write into a live external financial system — treat with the same care as any other hard-to-reverse action in this codebase

**Engineer B (owns ENH-012):**
- Dashboards on `gold_matched_invoices` / `gold_exceptions` / `gold_reconciliation_summary`
- RULE-03 applies to any new measure: KPI cards must live-query `gold_exceptions`, never trust the `gold_reconciliation_summary` snapshot directly

**Demo (Fri):** Force-matched exception pushed back to NetSuite with full audit trail; reporting dashboard live.

---

### Sprint 4, Week 8 (Oct 5–9) — Hardening → prod-testing ready

**Both engineers:**
- ENH-004 (Fabric migration finish): remaining four Recon tables (`jobs`, `exception_dispositions`, `users`, `ai_audit_log`) + Bronze/Silver/Gold. Scoped exactly per RULE-6/ARCHITECTURE.md §9 — table-group routing only, don't fold in unrelated fixes, flag (don't silently resolve) any transaction spanning two table groups. Sequenced last since it collides with both ENH-002 and ENH-008, now stable
- Full regression pass — confirm 281/281 non-environment-blocked tests still pass, no new failures
- Stand up a small golden-case evaluation harness (known statements → expected matches/exceptions) so regressions surface before UAT, not during it
- Security pass: grep repo-wide for any other hardcoded credentials, confirm the write-back approval gate can't be bypassed, confirm session hardening from Week 3 holds
- Supervised UAT with the client's team — real statements end to end, including live fetch and write-back paths
- Deployment runbook + rollback plan finalized
- **Spike only:** scope the CCC1 ingestion pipeline (connection exists, doesn't flow into a proper database yet) — produce a sizing estimate, don't attempt the build in this window
- Update `enhancements/REGISTRY.md` fully — everything that shipped moves IN BACKLOG → COMPLETE, honestly note anything that slipped

**Outcome:** Prod-testing-ready build.

---

## 4. Explicitly out of this window

| Item | Status | Detail |
|---|---|---|
| ENH-009 (Pass 3 AI Matching) | Blocked | Needs Sprint Lead sign-off on the INV-02 amendment (`docs/Claude.md` v2.8) — recommend resolving this in parallel during Week 1, since it's a governance action, not a build task. Not assumed anywhere in this schedule. |
| ENH-013 (Files/SharePoint Export) | Bumped to fast-follow | Moved out of Week 6 to make room for ENH-017 (write-back) in Week 7. Independent of everything else — safe to slot in whenever capacity opens. |
| CCC1 ingestion pipeline | Scoped only | Week 8 produces a sizing estimate; full build needs its own follow-on window. |
| Auto-forward email inbox intake | Needs confirmation | Not confirmed to exist in the current codebase — check early; if absent, it's a new item bolted onto ENH-001's existing Blob/Event Grid intake. |
| Admin/user management | Deprioritized | Per existing team decision. |
| Shop-level mismatch reporting, flexible filtering | Future items | No build slot in this window — natural fast-follow once ENH-012 ships. |

---

## 5. Reusable-components discipline (applies to ENH-002, ENH-005, ENH-008, ENH-015, ENH-017)

Per the Reusable Components requirement brief: the goal is not a generic reconciliation platform, but making sure a handful of clearly reusable pieces aren't hardcoded to Vive/NetSuite, so a future reconciliation build (bank, intercompany, another AP client) can reuse them without a rewrite. Concretely, for this window:

- **Run Manager (ENH-002):** core model (`run_id`, `reconciliation_type`, `source_scope`, `target_scope`, `run_status`, …) stays domain-blind. Vive-specific fields (`legal_entity`, `accounting_period`, `vendor_scope`, `AP_cutoff`) live inside `business_context`, not as core columns.
- **Document Registry (ENH-005):** generic artifact model (`artifact_id`, `artifact_type`, `content_hash`, `version`, `supersedes_artifact_id`, `validation_status`, `processing_status`); `artifact_type = vendor_statement` is Vive's value, not a hardcoded assumption in the registry itself.
- **Audit/Decision Ledger (ENH-008):** no NetSuite-specific columns as first-class fields — anything Vive-specific belongs inside `evidence`/`business_metadata`.
- **NetSuite adapters (ENH-015, ENH-017):** this is the textbook case for the brief's adapter boundary — NetSuite auth, endpoints, and record shapes live entirely inside the adapter module; the matching pipeline and ledger never import anything NetSuite-specific directly.
- **Non-goal, explicitly:** do not build a universal reconciliation config language or a metadata-driven generic UI in this window — per the brief, generalize only where the abstraction is already obvious; if it's unclear, build it for Vive and don't force it.

This doesn't change the schedule — it's a design constraint the owning engineer confirms at the start of each relevant week, same as any other Known Constraint in a brief.

---

## 6. Process checklist (per item, before it's "done")

Carried over from this repo's existing methodology — apply to every ENH above, including the three proposed new ones:
- [ ] Prompt 1 touch-point research done against live code + `discovery/` artifacts, brief moved from Draft to Signed Off
- [ ] Prompt 2 collision-surface analysis run for any pair building in the same week/sprint
- [ ] Any invariant or rule change (RULE-08, INV-02, etc.) recorded explicitly in `RULES.md`/`docs/Claude.md`, not decided implicitly in code
- [ ] New tables via a new numbered migration file only — never hand-edited DDL
- [ ] `enhancements/REGISTRY.md` updated on completion (status, sprint, collision surfaces resolved)
- [ ] Full pytest suite re-run, no new failures beyond the known 18 environment-specific ones

---

## 7. Definition of done — prod-testing ready (Oct 9)

- [ ] Live NetSuite fetch (ENH-015) integrated and reconciling
- [ ] Force-match with ranked candidates (ENH-016) live, writing to the audit ledger
- [ ] Write-back (ENH-017) live: sandbox-tested, approval-gated, fully logged
- [ ] ENH-002 through ENH-006, ENH-008, ENH-010 through ENH-014 all COMPLETE in the registry
- [ ] ENH-004 (Fabric migration) fully complete — no tables left on the old routing path
- [ ] No hardcoded credentials anywhere in the repo (verified by grep, not assumption)
- [ ] All five hard invariants (INV-01 through INV-05) re-verified against live code, all PASS
- [ ] Golden-case evaluation harness in place and passing
- [ ] Full pytest suite green (environment-specific failures excluded, same 18 as baseline or fewer)
- [ ] Supervised UAT complete with no blocking issues, including live fetch + write-back paths
- [ ] CCC1 ingestion scoped with a sizing estimate for the next window
- [ ] ENH-009 governance question (Sprint Lead review of INV-02) resolved one way or the other — not left indefinitely provisional
