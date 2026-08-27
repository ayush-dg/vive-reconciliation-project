# RISK_REGISTER.md — VIVE Reconciliation
Produced by: BCE Stage 2 Session E, Part 2 (CC, per Path A precedent) — fresh extraction
Date: 2026-08-05

Synthesized from `discovery/INVARIANT_CATALOGUE.md`, `discovery/MODULE_CONTRACTS.md`, `discovery/TOPOLOGY.md`, and `discovery/INTEGRATION_CONTRACTS.md` — no new source reads performed this pass, consistent with the methodology's instruction for this session; all "confirmed still true" statements below rest on the direct source reads already performed in Sessions A/F/B/C/G/D earlier this same day. Each entry carried forward from the archived register (`discovery/_archive_2026-07/RISK_REGISTER.md`) is re-stated against current M-NNN/IC-NNN numbering, not renumbered to match the archive — see `TOPOLOGY.md`'s header note on why this is a fresh baseline.

---

## R-001 — Confidence-gated human review remains defeated for the two dormant fallback-adjacent providers

**Severity:** Medium (downgraded from Critical — the active primary is fixed; residual risk is confined to providers with no live traffic)

**Description:** The system's core safety mechanism — any row with `line_confidence` below `0.60` must route to human review (IC-01) — depends on genuine, model-elicited confidence. Confirmed this session: the active primary, M-025 (Claude Sonnet), genuinely elicits per-row confidence via `_parse_confidence()`, with a documented fallback to `0.40` (below the review threshold) when the signal can't be trusted. **M-029 (Gemini) and M-030 (Mistral) still hardcode a flat `ROW_CONFIDENCE = 0.75`** — confirmed unchanged this session — which would always clear the review threshold regardless of actual quality if either were ever activated.

**Threatened invariant:** IC-01

**Affected modules:** M-025 (fixed), M-029, M-030 (still affected, dormant)

**Mitigation (current):** Neither dormant client is reachable except via an explicit `get_ai_client("gemini"|"mistral")` call — no code path in this system does so today.

**Recommended action:** Before either provider is ever reactivated (a swap, a fallback-chain addition, or an A/B comparison), port M-025's confidence-eliciting prompt/parsing pattern to whichever is being activated. Track this as a pre-activation checklist item, not a standing todo.

---

## R-002 — Missing totals-row filter in the two dormant LLM clients

**Severity:** Medium (downgraded from High — the active primary is fixed; residual exposure confined to dormant providers)

**Description:** M-025 (Claude Sonnet, active primary) now filters totals/summary rows via `_is_totals_row()` — confirmed this session, unchanged since the archived fix. **M-029 (Gemini) and M-030 (Mistral) still have no equivalent filter** — confirmed unchanged.

**Threatened invariant:** IC-03

**Affected modules:** M-025 (fixed), M-029, M-030 (still affected, dormant)

**Mitigation (current):** Same as R-001 — dormant, unreachable except via explicit provider name.

**Recommended action:** Same as R-001 — a joint pre-activation checklist item for both remaining bugs on the same two dormant clients, since reactivating either without addressing R-001/R-002 together would reintroduce both simultaneously.

---

## R-003 — Reprocessing the same document produces genuine row-level duplication in Gold tables

**Severity:** Medium

**Description:** Every intake run generates a fresh `statement_id` and writes an independent set of Silver/Gold rows — confirmed unchanged this session (M-017's `run_intake()`, M-034's `run_matching()`). No deduplication exists at the Silver/Gold layer, only at the AI-extraction-cost layer (IC-09's cache). The dashboard's headline KPIs (M-003's `get_kpis()`) are protected incidentally, via a `_LATEST_RUN_PER_VENDOR` join that exists for "show current state" reasons, not as deliberate anti-duplication design — confirmed this join is still present and still the only thing preventing double-counted totals on the primary dashboard view.

**Threatened invariant:** None formal — a data-model gap, not a violated invariant.

**Affected modules:** M-017 (source of the gap), M-003 (`get_kpis()` — incidental protection; `get_all_runs()` — unprotected, confirmed still true)

**Mitigation (current):** `_LATEST_RUN_PER_VENDOR`, incidentally, on the dashboard KPI view and recent-runs view; NOT applied to `get_all_runs()` (the Reports page), which would show duplicate-looking entries for the same vendor/period.

**Recommended action:** Unchanged from the archived recommendation — document explicitly, in code, that `_LATEST_RUN_PER_VENDOR` is load-bearing for duplicate-upload safety wherever it's used, so a future refactor doesn't remove it without recognizing the connection; separately decide whether "each upload is an independent reconciliation run" is the intended permanent model.

---

## R-004 — No liveness/watchdog on the background worker thread; no stale-job requeue logic

**Severity:** Medium

**Description:** Confirmed unchanged this session (M-005's Known Fragility, B05) — a job stuck in PROCESSING is never automatically requeued. The worker-pool scoping (per-`pdf_filename`, IC-05) still means a stuck job only blocks new claims for that same filename, not the whole queue — this narrowing is confirmed still in effect, unchanged since the archived record.

**Threatened invariant:** IC-05

**Affected modules:** M-005, M-003

**Mitigation (current):** The 30-minute subprocess timeout (`_run_job()`) bounds most hang scenarios; per-filename scoping (not system-wide) bounds the blast radius of any stall that does occur.

**Recommended action:** Unchanged — implement stale-job requeue logic (a job PROCESSING past a timeout with no corresponding subprocess still running gets automatically reset to PENDING or FAILED).

---

## R-005 — The job pipeline depends on an untested, untyped string contract between the orchestrator's print output and the worker's regex parser

**Severity:** Medium

**Description:** Confirmed unchanged this session — `scripts/run_full_pipeline.py` (M-021) prints `"Statement ID: {statement_id}"` as its only mechanism for communicating the result back to `web/worker.py` (M-005), which extracts it via `STATEMENT_ID_RE`. No test asserts this contract holds; a reformatting of that one print line would silently misreport a successful job as FAILED.

**Threatened invariant:** IC-05 (the same claim-and-record mechanism this contract feeds into)

**Affected modules:** M-021 (producer), M-005 (consumer)

**Mitigation (current):** None — purely incidental that this hasn't broken yet.

**Recommended action:** Unchanged — replace the string-based signal with a structured one (a small JSON result file, or a version-stamped machine-readable line).

---

## R-006 — Schema provisioning across three storage surfaces now, not two, with no automated sync check for any of them

**Severity:** Medium, with a widened description this session

**Description:** Confirmed unchanged for the original two-surface gap — `src/lakehouse/migrations.py` (M-038) is the tracked source of truth for SQLite; `src/lakehouse/azure_sql_migrations.py` (M-039) is a manually-maintained T-SQL mirror with no automated check that the two agree (confirmed this session, in sync as of the direct comparison performed in Session F01). **Widened this session:** the Fabric Warehouse cut-over (three tables) adds a **third** schema surface with **no schema-creation or tracking mechanism in this codebase at all** — see `INTEGRATION_CONTRACTS.md` IP-011's Gaps #1. `scripts/test_fabric_connection.py` (M-045) can only observe what's already there via `INFORMATION_SCHEMA.TABLES`; nothing creates or evolves it.

**Threatened invariant:** IC-14, IC-15

**Affected modules:** M-038, M-039, M-037, M-045

**Mitigation (current):** SQLite ↔ Azure SQL confirmed in sync as of this session's direct comparison. Fabric side: unknown — no mechanism exists to check it against either of the other two.

**Recommended action:** (1) Unchanged from the archived recommendation for the SQLite/Azure SQL pair — an automated diff check. (2) **New:** establish some tracked provisioning mechanism for the Fabric side (even a manually-run, version-controlled DDL script would be better than the current total absence), and add a fourth automated check comparing it against the other two.

---

## R-007 — Hardcoded fallback admin credential in `web/routers/auth.py`

**Severity:** High

**Description:** Confirmed unchanged this session (M-006, B06's Known Fragility) — `FALLBACK_EMAIL`/`FALLBACK_PASSWORD`/`FALLBACK_NAME` remain live in `_authenticate()`, with no tracked removal trigger or date. The literal value is deliberately not reproduced in this or any `discovery/` artifact. `migrations/004_add_users_table.sql`'s header comment (not re-read verbatim this session but not touched by any commit since the archived record) is understood to still carry the same value per the archived finding.

**Threatened invariant:** None formal — a candidate for a future invariant.

**Affected modules:** M-006; `migrations/004_add_users_table.sql` (not a registered module)

**Mitigation (current):** None.

**Recommended action:** Unchanged — remove entirely, or gate behind an explicit, default-off `DEBUG`/`DEV_MODE` check.

---

## R-008 — Hardcoded session secret default in `web/app.py`

**Severity:** High

**Description:** Confirmed unchanged this session (M-001, B01's Known Fragility) — `WEB_SESSION_SECRET` falls back to a hardcoded literal if unset; not verified this session whether it's since been added to `.env`/`.env.example` (not re-read this pass) — carried forward as still open pending that specific re-check.

**Threatened invariant:** None formal.

**Affected modules:** M-001

**Mitigation (current):** The environment-variable override path exists and works — the gap is operational (is it actually configured?), not structural.

**Recommended action:** Unchanged — set a real generated value per deployment, document it in `.env.example`, and make the hardcoded default loudly rejected outside local dev.

---

## R-009 — Event Grid auto-intake webhook: fixed in code, deployment status not re-verified this session

**Severity:** Fixed in code (2026-07-25) — deployment status unknown as of this session

**Description:** Confirmed the code-side fix remains in place this session (M-015, B15's Known Fragility: shared-secret auth, container-pinning, request cap all present and unchanged). **Not re-verified this session:** whether `VIVE_EVENTGRID_WEBHOOK_SECRET` has since been generated and configured on the actual Azure Event Grid subscription (per `TOPOLOGY.md`'s Engineer Review item 5, this was blocked on Azure RBAC permissions pending Ashrith as of the archived record — current status not checked this pass).

**Threatened invariant:** None formal.

**Affected modules:** M-015, M-043

**Mitigation (current):** Fails closed (401) by design if unconfigured — the correct safe default regardless of deployment status.

**Recommended action:** Confirm current deployment status directly with whoever owns the Azure Event Grid subscription before assuming either "still blocked" or "since resolved."

---

## R-010 — AI-call concurrency limiter permanently loses a slot if a process holding one is killed

**Severity:** Medium

**Description:** Confirmed unchanged this session (M-041, G05's Known Fragility) — a killed (not normally-exited) process never releases its lock file; capacity shrinks by one until manually cleaned up.

**Threatened invariant:** IC-06

**Affected modules:** M-041

**Mitigation (current):** None automated — same accepted-tradeoff posture as before.

**Recommended action:** Unchanged — a PID-liveness check on slot acquisition, only if this becomes an observed operational problem, not built ahead of one.

---

## R-011 — `friendly_dt()` (`web/deps.py`) hardcodes IST for all displayed timestamps

**Severity:** High

**Description:** Confirmed unchanged this session (M-002, B02's Known Fragility) — every displayed timestamp converts to hardcoded IST regardless of the actual audience's location; storage remains correctly UTC. Still the single most-referenced unfixed finding across this entire session's work, independently re-surfaced at multiple points (INTAKE_SUMMARY.md, TOPOLOGY.md, MODULE_CONTRACTS.md).

**Threatened invariant:** None formal.

**Affected modules:** M-002

**Mitigation (current):** None.

**Recommended action:** Unchanged — make the display timezone configurable via an env var (e.g. `VIVE_DISPLAY_TIMEZONE`, default US Eastern).

---

## R-012 — Fabric Warehouse cut-over: concurrency-unsafe `id` assignment on three tables, no schema-provisioning mechanism

**Severity:** High — new this session

**Description:** The Fabric Warehouse cut-over (`extraction_cache`, `document_intake_log`, `validation_document_review_queue`, landed `7bd6c9f` and confirmed extended by direct code read this session — the earlier assumption that it was scoped to `extraction_cache` alone was itself a divergence corrected in `TOPOLOGY.md`) introduces two compounding, currently-unmitigated gaps: (1) each of the three tables lost its `IDENTITY` property on the Fabric side (Fabric's IDENTITY only supports BIGINT with large non-sequential values, incompatible with the already-migrated rows' small sequential ids) — every write site (M-003, M-017) computes `MAX(id) + 1` in application code with no lock or transactional guarantee, confirmed by each function's own docstring acknowledging this explicitly; (2) no schema-creation or tracking mechanism exists for the Fabric side at all — see R-006.

**Threatened invariant:** IC-19 (currently NO — this is the invariant that should hold but doesn't), IC-15 (PARTIAL)

**Affected modules:** M-003, M-017, M-037, M-045

**Live confirmation:** Not observed to have actually caused a collision in this session's checks (no live database was queried this session — no local `lakehouse/reconciliation.db` exists in this checkout). This is a **real, structural exposure**, not a confirmed incident — same evidentiary posture the archived register used for R-002.

**Mitigation (current):** None. The exposure requires two writers to the same table computing their next `id` at the same instant — plausible under real concurrent worker-pool load (M-005 runs up to `VIVE_WORKER_POOL_SIZE` workers, each capable of writing to these tables during intake) but not yet observed.

**Recommended action:** Before this system carries meaningful concurrent load: (1) add a real sequence/identity mechanism on the Fabric side, or move id-assignment to a single-writer/locked pattern; (2) stand up some tracked provisioning script for the Fabric schema, even a simple version-controlled one; (3) decide whether execute_sql_fabric()/execute_query_fabric() should gain the same connection-drop retry `execute_sql()`/`execute_query()` already have, given Fabric Warehouse is also cloud infrastructure subject to the same class of transient connection issues Azure SQL's retry logic exists for.

---

## R-013 — Exceptions router's route-registration order is a silent-failure trap for future changes

**Severity:** Low — currently correctly enforced, flagged for durability, not because it's broken today

**Description:** `web/routers/exceptions.py` (M-008) must declare its two fixed-suffix POST routes (`/bulk-approve`, `/escalate`) before its generic `POST /exceptions/{vendor_name:path}` handler — confirmed correctly ordered this session. Starlette's `:path` converter matches greedily; a future engineer adding a new action route below the generic one would silently misroute requests into `vendor_name` with no error, no test failure signal identified this session (not confirmed whether a route-order-specific test exists).

**Threatened invariant:** IC-18

**Affected modules:** M-008

**Mitigation (current):** An inline code comment documents the requirement directly at the point of risk — the best available mitigation short of an automated test.

**Recommended action:** Consider a lightweight route-order test (assert the app's route table has the two fixed-suffix routes before the generic one) so a future violation fails loudly in CI rather than silently in production.

---

## Summary Table

| Risk ID | Description | Severity | Threatened Invariant | Affected Modules |
|---|---|---|---|---|
| R-001 | Confidence gate defeated for 2 dormant providers (Gemini, Mistral) — active primary fixed | Medium | IC-01 | M-025 (fixed), M-029, M-030 |
| R-002 | Missing totals-row filter, same 2 dormant providers — active primary fixed | Medium | IC-03 | M-025 (fixed), M-029, M-030 |
| R-003 | Duplicate-upload row-level duplication in Gold tables | Medium | — | M-017, M-003 |
| R-004 | No worker liveness/watchdog, no stale-job requeue | Medium | IC-05 | M-005, M-003 |
| R-005 | Fragile "Statement ID:" string contract | Medium | IC-05 | M-021, M-005 |
| R-006 | Schema provisioning across 3 surfaces (SQLite/Azure SQL/Fabric), no automated sync check for any | Medium | IC-14, IC-15 | M-038, M-039, M-037, M-045 |
| R-007 | Hardcoded fallback admin credential in auth.py | High | — | M-006 |
| R-008 | Hardcoded session secret default in app.py | High | — | M-001 |
| R-009 | Event Grid webhook auth — fixed in code, deployment status not re-verified | Fixed in code / deployment unknown | — | M-015, M-043 |
| R-010 | AI-call concurrency limiter loses a slot on process kill | Medium | IC-06 | M-041 |
| R-011 | friendly_dt() hardcodes IST for all displayed timestamps | High | — | M-002 |
| R-012 | Fabric cut-over: concurrency-unsafe id assignment + no schema-provisioning mechanism | High | IC-19, IC-15 | M-003, M-017, M-037, M-045 |
| R-013 | Route-registration-order silent-failure trap (currently correct, fragile) | Low | IC-18 | M-008 |

Session E is complete. `INTEGRATION_CONTRACTS.md` and `RISK_REGISTER.md` must be committed before the Stage 2 Completeness Summary is produced.
