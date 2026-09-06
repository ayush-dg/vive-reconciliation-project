STAGE-1-DRAFT: DOCS-DERIVED — 2026-09-01 — Produced by BCE Adapter Pipeline Stage 1
STAGE-2-STATUS: R-004 through R-007 added — 2026-09-02, BCE Adapter Pipeline Stage 2 Session
E (Integration Contracts + Risk Register). New entries are code-confirmed findings surfaced
by Sessions A–D's source reading, evaluated here for whether they rise to risk-register level
(operational/business risk) versus remaining a module-contract-level fragility note. One
candidate from this session's evaluation list (the Fabric DDL missing `IF NOT EXISTS`) was
considered and NOT added — see the note after R-007.
STAGE-3-STATUS: CHECK 0 (schema compliance) found and fixed two P1 SCHEMA_VIOLATIONs —
2026-09-02. R-001–R-003 were missing `Affected modules:` fields (present on R-004–R-007);
backfilled. R-001 cited "N2" in its threatened-invariant framing as if it were a resolvable
`INVARIANT_CATALOGUE.md` ID; it isn't (confirmed — no such ID exists there) — reworded to
state plainly that N2 is a `PHASE4_GATE_RECORD.md` label deliberately never promoted to a
catalogue entry, not an orphaned reference. Cross-artifact review (P1-S3-003, P2-S3-006)
also found R-002/R-003 didn't cross-reference `docs/INVARIANTS.md`'s OD4/OD5, despite
covering the same underlying gaps — both now cross-referenced. R-008 added 2026-09-02,
resolving P1-S3-002: the engineer checked `.env` directly and found `FABRIC_SQL_ENDPOINT`
is a bare hostname, not a valid connection string — confirmed by CC against the real
parser, this is the actual root cause of Fabric never having worked, not merely an
unanswered auth question. See
`discovery/ANNOTATION_CHECKLIST.md` for the full Stage 3 backlog.

# RISK_REGISTER.md — VIVE Statement Reconciliation

Seeded per BCE convention: one entry for each ACCEPT-disposed finding in
`docs/PHASE4_GATE_RECORD.md` Section D, plus a stub entry (severity NOT DETERMINABLE FROM
SOURCE) for each key risk in `docs/ARCHITECTURE.md` §4 that isn't already covered by a
PHASE4_GATE_RECORD.md disposition. Section D's own severity scale (BLOCKER/HIGH/MEDIUM/LOW)
is mapped to P1/P2/P3 as: BLOCKER→P1, HIGH→P2, MEDIUM/LOW→P3. Note: Section D's 5 BLOCKER
and 1 HIGH findings besides #7 are all disposed **RESOLVE**, not ACCEPT — closed by a
concrete doc/plan change, so they are not carried into this live risk register (their
resolution is recorded in `PHASE4_GATE_RECORD.md` itself, which remains the authoritative
history). Only genuinely still-open risk is catalogued here.

---

- **Risk ID:** R-001
- **Description:** `docs/PHASE4_GATE_RECORD.md`'s brief non-negotiable **N2** ("never call
  NetSuite/CCC live from matching") has no enforcing invariant — the original GLOBAL
  invariant enforcing this was removed 2026-08-17. `EXECUTION_PLAN.md` Task 5.2 itself
  states this is "no longer an enforced invariant, only a design convention." A brief
  non-negotiable currently has no hard enforcement behind it. **N2 is a
  `PHASE4_GATE_RECORD.md` label, not an ID in `INVARIANT_CATALOGUE.md`'s own G/S/T/
  IC-CANDIDATE namespace** — deliberately never promoted there, per the Mitigation below;
  this is stated explicitly to avoid it reading as an orphaned/unresolved cross-reference
  (Stage 3 CHECK 0 finding P1-S3-002).
- **Severity:** P2 (source: HIGH, `PHASE4_GATE_RECORD.md` Section D Finding #7)
- **Affected modules:** M-026 (`deterministicMatching.ts`) — the module that would need a
  live-call guard if a future task ever added a live NetSuite/CCC pull matching mode; no
  current module violates N2 (no live-API code path exists in this build at all), so this
  names where the guard would go, not a module currently breaking the rule.
- **Source artifact:** `docs/PHASE4_GATE_RECORD.md` Section D, Finding #7
- **Mitigation:** Engineer accepted rationale (verbatim intent): "still true but not needed
  to be defined." N2 remains true by construction — Task 5.2's matching only ever queries
  `silver.statement_line`/Silver reference data; no live-API code path exists anywhere in
  the current plan to guard against. Accepted as a documented convention, not re-promoted
  to an enforced/tested invariant — this is a deliberate decision, not a gap to close.
- **Recommended action:** NOT DETERMINABLE FROM SOURCE (requires operational assessment).
  Docs do state a revisit trigger: re-evaluate if a future task ever introduces the "live
  NetSuite/CCC pull as an alternative matching mode" item already tracked in
  `ARCHITECTURE.md` §7's Parking Lot — at that point, add a real catalogue entry and point
  its enforcement point at M-026.

- **Risk ID:** R-002
- **Description:** Version-chaining (D-H, amended 2026-08-26) has no human checkpoint at
  all — a genuinely conflicting (not corrective) statement for the same vendor/period
  silently supersedes the prior one with no flag raised. `ARCHITECTURE.md` §4 itself
  describes this as "a real gap for BCE to close, and a sharper one than before the
  2026-08-26 amendment — worth explicit sign-off rather than treating as equivalent risk."
- **Severity:** NOT DETERMINABLE FROM SOURCE
- **Affected modules:** M-021 (`vendorIdentification.ts`) — `runVersionChaining`
  (confirmed at `src/lib/vendorIdentification.ts:137`, per
  `discovery/components/A02_module_call_map.md`'s call table) is the actual implementing
  code; this risk describes a design gap in that function's behavior (no checkpoint), not
  a defect Stage 2 otherwise flagged independently.
- **Source artifact:** `docs/ARCHITECTURE.md` §4 Key Risks, item 1 (not covered by any
  `PHASE4_GATE_RECORD.md` Section D finding — no matching entry found there).
  **[Stage 3 cross-reference, 2026-09-02]:** this is the same gap `docs/INVARIANTS.md`
  OD4 already names directly — OD4's own text: "Not silently accepted — raised for
  Vaishali/Vartan to confirm this trade is intentional before build." R-002's resolution
  is contingent on that same conversation, not a separate open item to track twice.
- **Mitigation:** none stated — this risk is recorded as currently unmitigated, not
  accepted-with-rationale like R-001.
- **Recommended action:** Confirm with Vartan (per OD4) whether version-chaining with no
  human checkpoint is an intentional, accepted trade. `ARCHITECTURE.md` frames this as
  BCE-scope to close, but OD4 makes clear it's also pending an explicit sign-off before
  build, not solely a future-BCE concern.

- **Risk ID:** R-003
- **Description:** Access-scoping deferral (D-F) could surface a real architectural need
  late — if a future UI Discovery pass reveals users genuinely need entity-partitioned
  access, not just a screen filter, that would be a Phase 2 loop-back, not a cosmetic fix.
  Partially resolved 2026-09-01 by removing the Legal Entity picker (auto-assigned a single
  fixed default) — but this resolves the *symptom* (an unresolved UI field), not the
  underlying open question about whether real multi-entity access scoping is eventually
  needed.
- **Severity:** NOT DETERMINABLE FROM SOURCE
- **Affected modules:** none currently — this is honestly a missing-feature gap, not a
  defect in an existing module: no module implements entity-scoped *access control*
  anywhere in this codebase. The nearest related modules are M-042 (`legalEntities.ts`)
  and M-070 (`UploadForm.tsx`), which handle legal-entity *assignment* at upload time (now
  a fixed positional default per R-007) — assignment, not access scoping, and not the same
  concern this risk describes.
- **Source artifact:** `docs/ARCHITECTURE.md` §4 Key Risks, item 4 (not covered by any
  `PHASE4_GATE_RECORD.md` Section D finding — no matching entry found there); related to
  the still-open OD5/D-F item in `ARCHITECTURE.md` §6 Open Questions. **[Stage 3
  cross-reference, 2026-09-02]:** directly ties to `docs/INVARIANTS.md` OD5, which states
  the entity-scoped access model "remains genuinely open" — no separate named approval
  pending the way R-002/OD4 has, so no action needed here until a future UI Discovery
  pass surfaces a real need, per OD5's own text.
- **Mitigation:** none stated.
- **Recommended action:** NOT DETERMINABLE FROM SOURCE (requires operational assessment).

- **Risk ID:** R-004
- **Description:** A failed Microsoft Fabric SQL connection attempt permanently caches the
  *rejected* promise in `db.ts`'s (M-003) module-level `fabricPoolPromise` singleton. Every
  subsequent `getFabricPool()` call for the life of the process returns that same rejection —
  there is no automatic retry, and no operator-facing signal distinguishing "Fabric was never
  configured" (deliberate SQLite fallback) from "Fabric was configured and the connect
  failed" (silent permanent breakage). Only an explicit `closeDb()` call resets it. This
  single connection pool serves both IP-002 (`recon`) and IP-004 (`silver` writes), so one
  transient connectivity blip at process startup can break both simultaneously.
- **Severity:** P2 — no data corruption, but a self-inflicted, non-self-healing outage of the
  primary transactional store with no automated recovery path.
- **Source artifact:** `discovery/components/G03_db.md` (M-003's own `[NOTABLE]` Known
  Fragility); `discovery/INTEGRATION_CONTRACTS.md` IP-002/IP-004 (Error handling assumptions,
  Known divergences).
- **Mitigation:** none — newly surfaced. `closeDb()` exists as a manual reset mechanism but
  requires an operator to already know the pool is poisoned and take deliberate action; there
  is no automatic detection or retry.
- **Recommended action:** either retry the connect with backoff instead of caching a
  rejection, or at minimum log/alert distinctly when `fabricPoolPromise` is in a rejected
  state so an operator knows to call `closeDb()`. Affected modules: M-003 (all 20 of its
  callers transitively). No cataloged invariant is directly threatened (this is availability,
  not correctness), but it undermines IP-002 and IP-004 identically since both share the one
  pool.

- **Risk ID:** R-005
- **Description:** **[NARROWED 2026-09-06, SPRINT-001 BCE refresh, ENH-001 Task 2.1 — see
  IC-CANDIDATE-01 for the full before/after]** The two G5 "no concurrent double-processing"
  lock implementations still recover from an unhandled failure asymmetrically, but the gap
  is now materially smaller. Matching's lock (M-017,
  `acquireMatchingLock`/`LOCK_STALE_AFTER_MINUTES`) self-releases and is TTL-reclaimable, as
  before. Extraction's lock (M-015/M-046, the `extracted_document.status='processing'` flip)
  now DOES recover from any in-process JS exception (a caught error resets status back to
  `'registered'`) — ENH-001 Task 2.1. The residual trigger is narrower: only a true
  OS-level process crash or restart (not a caught exception) still leaves the document
  permanently stuck in `'processing'`, with `triggerExtraction`'s own guard (`WHERE status !=
  'processing'`) then rejecting every future Extract attempt indefinitely. When it does
  still occur, the consequence is unchanged — only direct DB intervention recovers it.
  Formally identified as IC-CANDIDATE-01 in `INVARIANT_CATALOGUE.md`.
- **Severity:** P2 (unchanged) — the trigger frequency dropped (only a process crash, not
  any exception, now causes this), but the impact when it does occur is identical to
  before: blocks the end user from ever re-attempting extraction on an affected document
  with no self-service recovery, no data corruption (G1/S10's append-only guarantees hold
  regardless). Severity is scored on impact, not frequency, per this register's existing
  convention (no finer-grained tier exists here to reflect a frequency-only change).
- **Source artifact:** `discovery/INVARIANT_CATALOGUE.md` IC-CANDIDATE-01; M-015's and
  M-046's own Known Fragility fields in `MODULE_CONTRACTS.md` (both updated 2026-09-06);
  `S2_VERIFICATION_RECORD.md` Task 2.1 TC-4/TC-5/TC-6/TC-7.
- **Mitigation:** Task 2.1's finally-block-equivalent reset closes the in-process-exception
  case. The residual case (process crash) has no mitigation yet.
- **Recommended action:** give the extraction lock the same self-releasing/TTL-reclaimable
  design as the matching lock (`src/lib/extraction.ts`, contrast against
  `matchingInvocation.ts:39,48-58`) to close the residual process-crash case too, or at
  minimum add an admin-facing "unstick" action. Affected modules: M-015, M-046 (partial
  recovery, in-process exceptions only); M-017, M-047 (full recovery, for contrast).
  Threatened invariant: IC-CANDIDATE-01 (G5 itself is not violated — its narrower "no two
  concurrent owners" guarantee still holds on both sides).

- **Risk ID:** R-006
- **Description:** `/api/matching/run-batch` (M-053), documented as the receiving endpoint
  for n8n's external scheduled trigger (IP-005), is not excluded from `proxy.ts`'s (M-043)
  session-auth matcher the way `/api/health` (M-051) explicitly is. Every request to it —
  including n8n's — must carry a valid browser session cookie or gets redirected to `/login`
  before the handler runs. n8n, as a machine-to-machine external scheduler with no browser,
  has no documented way to obtain or present that cookie, and no compensating machine-auth
  mechanism (API key, shared secret, service token) exists anywhere in source for this route.
  As coded, this build's only non-manual matching trigger path appears unreachable by its own
  documented caller. Now formally identified as IC-CANDIDATE-03 in `INVARIANT_CATALOGUE.md`.
- **Severity:** P1 — if accurate, the scheduled/batch matching integration this build was
  built to support cannot function without an out-of-band workaround invisible to source
  (and even a hand-provisioned cookie would need refreshing well inside M-043's 30-minute
  idle timeout for any real monthly-cadence job — see `INTEGRATION_CONTRACTS.md` IP-005
  Gaps).
- **Source artifact:** `discovery/INVARIANT_CATALOGUE.md` IC-CANDIDATE-03;
  `discovery/components/U11_matching_run_batch_route.md`'s own `[NOTABLE]` tag;
  `discovery/INTEGRATION_CONTRACTS.md` IP-005 (Auth mechanism, Known divergences).
- **Mitigation:** none — newly surfaced.
- **Recommended action:** exclude `/api/matching/run-batch` from M-043's auth matcher (the
  pattern M-051/`/api/health` already establishes) and add a compensating machine-auth
  mechanism before this integration is relied on operationally. Affected modules: M-053,
  M-043. Threatened invariant: IC-CANDIDATE-03.

- **Risk ID:** R-007
- **Description:** `UploadForm.tsx`'s (M-070) `DEFAULT_LEGAL_ENTITY_ID = LEGAL_ENTITIES[0].id`
  is now the *only* legal entity every uploaded document is attributed to — legal entity is
  no longer user-selectable at all (an engineer-directed simplification, 2026-08-30). No
  `isDefault`/priority marker exists on the static `LEGAL_ENTITIES` array
  (`legalEntities.ts`, M-042); the default is derived purely from array position. Reordering
  that array — a plausible, easy-to-make change (e.g. adding a new entity alphabetically
  ahead of the current one) — would silently reassign every subsequent upload's legal entity
  with no test, type, or runtime guard to catch it. Now formally identified (together with an
  unrelated vendor-extractor-routing instance of the same pattern) as IC-CANDIDATE-02 in
  `INVARIANT_CATALOGUE.md`.
- **Severity:** P2 — silent business-data misattribution risk (legal entity feeds
  reconciliation/reporting), made worse specifically because the field is no longer
  user-visible or user-correctable at upload time the way it would be if still selectable.
- **Source artifact:** `discovery/INVARIANT_CATALOGUE.md` IC-CANDIDATE-02 (legal-entity half);
  `MODULE_CONTRACTS.md`'s M-042 and M-070 rows.
- **Mitigation:** none — newly surfaced. S4 (a document is never registered without *a*
  `legal_entity_id`) is satisfied regardless — it guards presence, not correctness of value —
  so it does not mitigate this risk.
- **Recommended action:** replace the positional default with an explicit `isDefault` marker
  on the `LEGAL_ENTITIES` record (or reintroduce an explicit selector before a second legal
  entity is ever added to the array). Affected modules: M-042, M-070, M-044 (also imports
  `LEGAL_ENTITIES`). Threatened invariant: IC-CANDIDATE-02.

- **Risk ID:** R-008
- **Description:** `FABRIC_SQL_ENDPOINT` (this build's IP-002, `recon` database connection)
  is confirmed malformed in this environment's `.env` — a bare hostname
  (`<workspace>.datawarehouse.fabric.microsoft.com`), not the ADO-style
  `Key=Value;Key2=Value2` connection string `db.ts:56`'s
  `new sql.ConnectionPool(endpoint)` requires. Verified directly: `mssql`'s underlying
  parser (`@tediousjs/connection-string`'s `parseSqlConnectionString()`) returns `{}` for
  a bare hostname — no error, no server, no auth block, nothing. `getDbMode()` treats any
  non-empty `FABRIC_SQL_ENDPOINT` as `'fabric'` mode regardless of content, so having this
  var set at all (even malformed) routes the app away from the working SQLite fallback
  into a path guaranteed to fail. This is the actual, confirmed root cause of why Fabric
  access has never worked in any session to date — not merely an unanswered auth
  question (which is what this was originally recorded as, `ANNOTATION_CHECKLIST.md`
  P1-S3-002).
- **Severity:** P1 — this build's own primary transactional store (`recon`) cannot
  currently connect to live Fabric at all, under any circumstances, until this value is
  corrected. Directly compounds R-004: a malformed string means `.connect()` fails on
  literally the first request, immediately triggering R-004's permanent pool-poisoning
  bug.
- **Affected modules:** M-003 (`db.ts`, the connection owner) and, transitively, every one
  of its 20+ callers across the serving/pipeline/route layers.
- **Source artifact:** Engineer-confirmed directly against `.env`, 2026-09-02; parser
  behavior verified directly by CC against the real `@tediousjs/connection-string`
  package in this repo's `node_modules`. See `TOPOLOGY.md` IP-002 and
  `INTEGRATION_CONTRACTS.md` IP-002 for the full technical trace.
- **Mitigation:** none — newly discovered. The local SQLite fallback means this has never
  caused a visible failure in any session, since `FABRIC_SQL_ENDPOINT` has presumably
  never been set during actual local dev/test runs in this sandbox (only present in this
  `.env` file, not necessarily exported to the process during `npm run dev`/tests —
  `playwright.config.ts` additionally force-blanks it for the Playwright-launched server
  specifically, so UI test runs are unaffected regardless).
- **Recommended action:** Reformat `FABRIC_SQL_ENDPOINT` as a proper ADO connection
  string once the correct auth scheme is decided (SQL auth, Azure AD Managed Identity, or
  an explicit AAD service-principal flow matching IP-003's `FABRIC_CLIENT_ID`/
  `FABRIC_CLIENT_SECRET`/`FABRIC_TENANT_ID` pattern) — e.g.
  `Server=<hostname>;Database=recon;Authentication=Active Directory Default;` for Managed
  Identity, or an explicit `User Id=`/`Password=` pair for SQL auth. This is now a
  concrete, scoped fix, not an open research question.

- **Risk ID:** R-009
- **Description:** **[NEW 2026-09-06, SPRINT-001 BCE refresh, ENH-001 Task 1.4]**
  `formatUploadTimestamp()` (M-068 `HomeView.tsx`, M-070 `UploadForm.tsx`) converts stored
  UTC `upload_timestamp` values to IST (`Asia/Kolkata`) for display via
  `Date.prototype.toLocaleString(..., { timeZone: 'Asia/Kolkata' })`. This relies on the
  Node runtime having full ICU data compiled in — verified working in local dev and in
  every Playwright test run (Node's local/dev build includes full ICU by default), but
  **never verified against the actual Azure App Service deployment target**. A Node build
  without full ICU either silently falls back to UTC (wrong display, no error — the worse
  failure mode) or throws a `RangeError` on an unsupported timeZone value, depending on the
  specific runtime build. Flagged at Task 1.4's own challenge-agent review as "a
  deployment-environment risk outside what a Playwright test against the dev server can
  verify," but never promoted to a risk-register entry until this refresh.
- **Severity:** P2 — if it manifests as silent UTC fallback, this is the same class of
  risk as R-006 (silent business-data misrepresentation): every timestamp shown on Home and
  Upload would be wrong by exactly the IST offset (5:30), plausible-looking and easy to
  miss, not a crash. (If it manifests as a thrown error instead, actual severity would be
  higher — but the "silent wrong data" mode is judged more likely for a missing-ICU Node
  build based on common Intl polyfill/fallback behavior, hence P2 rather than P1.)
- **Affected modules:** M-068 (`HomeView.tsx`), M-070 (`UploadForm.tsx`) —
  `formatUploadTimestamp()` (duplicated verbatim in both, per `MODULE_CONTRACTS.md`'s own
  existing cross-cutting note on that duplication).
- **Source artifact:** `sessions/SPRINT-001/ENH-001/S1_VERIFICATION_RECORD.md` Task 1.4's
  BCE Impact section (challenge-agent finding, added retroactively at this BCE refresh).
- **Mitigation:** none yet — not exercisable via a Playwright test against the local dev
  server, which always has full ICU.
- **Recommended action:** verify the actual Azure App Service Node runtime's ICU data
  includes `Asia/Kolkata` (either via a deployed smoke check, or by confirming the deployed
  Node build includes `full-icu`) before relying on this display in production. If the
  target runtime lacks full ICU, either bundle the `full-icu` package or switch to a
  manual UTC+5:30 offset calculation that doesn't depend on `Intl`/ICU data at all.

**Considered and not elevated: Fabric DDL missing `IF NOT EXISTS` (M-041/`vendorSchema.ts`).**
`vendorSchema.ts`'s Fabric-dialect DDL for per-vendor raw tables has no `IF NOT EXISTS` guard
(unlike its SQLite counterpart), contradicting its own "idempotent" doc comment — calling it
twice for the same vendor in Fabric mode would throw. This is real, but per the module's own
contract it is currently unreachable: no code path in this build exercises Fabric app-state
for vendor-table creation today (Fabric mode, where configured, is used for `recon`/`silver`
via M-003 and `bronze` reads via M-008, but nothing currently drives M-041's Fabric branch).
Unlike R-004/R-005/R-006/R-007 above — each of which is exercised by real, currently-live
usage (a configured Fabric pool, any extraction crash, the actual n8n integration, every real
upload) — this one has zero current trigger path. Keeping it as a documented fragility in
M-041's own module contract rather than promoting it here; it should be revisited and added
if/when any future work wires up Fabric app-state for vendor-table creation, at which point
it would become live risk rather than latent code-quality debt.

---

## Not carried into this register (context, not omission)

- `PHASE4_GATE_RECORD.md` Section D findings #8–#12 (MEDIUM/LOW) remain
  `*(engineer to disposition)*` — neither RESOLVE nor ACCEPT. Per the seeding rule ("for
  each ACCEPT decision... produce one risk entry"), an undispositioned finding is not yet
  an ACCEPT and is not catalogued here. If the engineer later dispositions any of them
  ACCEPT, this register should be updated at that time — flagged, not silently pre-empted.
- The verification-tooling non-idempotency finding and the S7 status-badge bug (both from
  `verification/VERIFICATION_CHECKLIST.md`, 2026-09-01) are real, open issues but are not
  ARCHITECTURE.md key risks or PHASE4_GATE_RECORD.md dispositions — they belong to Phase 8
  Part 1's own record, already tracked there, not duplicated into this register.
