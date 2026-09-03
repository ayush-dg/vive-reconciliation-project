STAGE-2-STATUS: NEW — 2026-09-02, BCE Adapter Pipeline Stage 2 Session E (Integration
Contracts + Risk Register, "CD" synthesis role). Produced entirely from already-committed
Stage 2 artifacts (`TOPOLOGY.md` A03, `MODULE_CONTRACTS.md`, `INVARIANT_CATALOGUE.md`, and
the four named component files) — no source code was read directly in this session. This is
an adversarial cross-read of artifacts Sessions A/B/C/D/G/U each produced independently;
several inconsistencies below are surfacing for the first time because this is the first
session to read A03 side-by-side with the component files that later superseded parts of it.

# INTEGRATION_CONTRACTS.md — VIVE Statement Reconciliation

One entry per IP-NNN (5 total, permanent IDs per `TOPOLOGY.md` A03). Each entry restates
what A03 and the owning module's contract independently claim, then calls out where they
disagree.

---

**IP-001 — Claude (Anthropic) via Azure AI Foundry**

Called by: M-028 (aiProvider.ts) directly; **also M-027 (aiResidualMatching.ts) directly** —
see Known divergences, this contradicts A03's own "reached transitively via M-028" framing.

What the application promises to send:
- Extraction path (M-028): PDF bytes as a `document` content block (`source.type: 'base64'`)
  plus the fixed `EXTRACTION_SYSTEM_PROMPT` constant (never concatenated with document
  content, per G3); model = `CLAUDE_MODEL_ID` (`'claude-sonnet-5'`) on the direct Anthropic
  path, or the Azure deployment name (`AZURE_CLAUDE_SONNET_DEPLOYMENT`) on the Foundry path.
- Residual-matching path (M-027, independent of M-028): the statement line + CCC/NetSuite
  reference data as `JSON.stringify`'d text content, plus its own fixed
  `RESIDUAL_SYSTEM_PROMPT` constant — same structural-separation discipline as M-028, but a
  second, independently-maintained enforcement site (per G3's catalogue entry).

What the application assumes it will receive:
- A `tool_use` response whose `input.lines` is an array matching `ExtractedStatement`/
  `ExtractedLine`. Two malformed shapes are explicitly guarded (not exceptions): a truncated
  response (`stop_reason === 'max_tokens'`) and a present-but-non-array `input.lines`, both
  degrade to `extracted: null` with a diagnostic `rawOutput` rather than crashing. All other
  response shapes/fields are ignored beyond what `parseRecordExtractionResponse` reads.

Auth mechanism:
[STAGE-2-DIVERGENCE - 2026-09-02] A03 states "NOT DETERMINABLE FROM SOURCE." This is now
stale relative to what Session C's own component read (`C08_aiProvider.md`) already
established: env-var API-key auth — `AZURE_CLAUDE_API_KEY` (+ endpoint + deployment name)
for the Foundry path, `ANTHROPIC_API_KEY` for the direct path — gated additionally by
`EXTRACTION_LIVE_TESTS === '1'` (a key alone is never sufficient). Azure Foundry is checked
before direct Anthropic; if both are configured, Foundry silently wins. A03 was never
revisited to absorb this once the component file existed.

Error handling assumptions:
Three-tier fallback per A03: Azure Foundry → direct Anthropic → deterministic mock,
selected by which credentials/opt-in flag are set. Neither live path in M-028 itself catches
API errors (auth, timeout, rate limit) — they propagate uncaught through M-021 (also
non-catching) to M-022's per-attempt try/catch, where they consume one of the S7 bounded-retry
attempts (max 2 total). The app therefore assumes any Claude-side failure is cheap to retry
once — there is no code that distinguishes a retryable failure (rate limit, timeout) from a
non-retryable one (bad API key, malformed request) before burning an attempt.

Known divergences:
- [STAGE-2-DIVERGENCE - 2026-09-02] A03 frames IP-001 as reached by M-021 and M-027
  "transitively" through M-028 ("the sole direct caller"). `MODULE_CONTRACTS.md`'s own M-027
  row and `INVARIANT_CATALOGUE.md`'s G3 entry both state the opposite directly: M-027 "makes
  its own direct Anthropic API call independent of M-028" and is "genuinely two separate,
  independently-maintained enforcement sites, not one shared path." A03's topology is wrong
  on this specific point — M-027 does not route through M-028 at all, it is a second direct
  caller of the same external system with its own credential/prompt surface.
- Auth staleness (above) — same underlying cause: A03's A03 section was written/confirmed at
  Session A before Session C's component-level detail existed, and was never re-synced.

Gaps:
- `shouldUseAzureFoundryExtraction()` gates only on `AZURE_CLAUDE_API_KEY` being set; it does
  not check `AZURE_CLAUDE_ENDPOINT`/`AZURE_CLAUDE_SONNET_DEPLOYMENT`. If either of those two
  is unset while the key and `EXTRACTION_LIVE_TESTS=1` are set, the non-null assertions in
  `extractViaAzureFoundryClaude` throw an opaque `URL`/`model: undefined` error at call time
  rather than a clear config error at the gate check — an operational trap for whoever
  configures the Foundry credentials.
- M-027 having an independent credential/call surface for the same external system means
  IP-001 effectively has two separate failure domains (Foundry/Anthropic keys could be valid
  for extraction but not residual matching, or vice versa) where A03 describes only one.

---

**IP-002 — Microsoft Fabric SQL database (`recon`)**

Called by: M-003 (db.ts)

What the application promises to send:
SQL statements (parameterized on values only — per M-006/schema.ts, neither the `mssql` nor
`tedious` driver supports parameterized identifiers, so table/column names are validated by
regex, not bound as parameters) issued through an `mssql` `ConnectionPool` opened against the
`FABRIC_SQL_ENDPOINT` connection string. No separate credential fields are visible at the
`db.ts` layer — whatever auth Fabric requires must be embedded in that single endpoint
string, or handled by driver/environment defaults not captured in any artifact read this
session.

What the application assumes it will receive:
A working `ConnectionPool` once `.connect()` resolves, then normal query result sets/row
counts for the ~20 callers that reach `recon_*`/`extracted_*` tables through it. The app
assumes a failed connect is retryable simply by trying again later — see Gaps, this
assumption is false as currently implemented.

Auth mechanism:
[STAGE-3-UPDATE — 2026-09-02, resolves ANNOTATION_CHECKLIST.md P1-S3-002]: **confirmed, not
undetermined.** The engineer checked this environment's `.env`: `FABRIC_SQL_ENDPOINT` holds a
bare hostname (`<workspace>.datawarehouse.fabric.microsoft.com`), not an ADO-style
`Key=Value;...` connection string. `db.ts:56` passes it straight into
`new sql.ConnectionPool(endpoint)`, which parses string input via
`@tediousjs/connection-string`'s `parseSqlConnectionString()`. Verified directly by CC:
that parser returns `{}` for a bare hostname — no error, no server, no auth block. So this
integration point currently has **no functioning connection configuration at all**, let
alone a determinable auth mechanism — the question "what auth does it use" doesn't yet
apply, because the string doesn't parse into anything usable in the first place. Contrast
with IP-003, which has a fully documented, functioning AAD client-credentials flow.
Promoted to `RISK_REGISTER.md` R-008.

Error handling assumptions:
[STAGE-2-DIVERGENCE - 2026-09-02] A03 states "NOT DETERMINABLE FROM SOURCE." Session G's own
component read (`G03_db.md`) already supersedes this: `getFabricPool()` throws an explicit
`Error` if `FABRIC_SQL_ENDPOINT` is unset (rather than silently falling back), and — the
module's own `[NOTABLE]` fragility — a failed `.connect()` leaves its *rejected* promise
permanently cached in the module singleton, so every subsequent caller gets the same
rejection with no automatic retry until `closeDb()` is explicitly invoked. A03's blanket "not
determinable" claim for this field was accurate at Session A but was never revisited once
Session G traced M-003 directly.

Known divergences:
- The error-handling staleness above. This same pattern — A03's IP-002 through IP-005 fields
  still reading as flat "NOT DETERMINABLE FROM SOURCE" while later component sessions
  actually determined several of them — recurs for IP-003 and IP-004 below; IP-001 was the
  only entry Session A itself tagged `[STAGE-2-UPDATE]`, and IP-002–005 were left as Stage 1
  text even though downstream sessions later gathered exactly this information. Flagging
  once here as the systemic cause rather than repeating the observation for each entry.

Gaps:
- The connection-pool permanent-cache bug is a genuine operational risk, not yet in
  `RISK_REGISTER.md` before this session — added as **R-004**.
- [Added 2026-09-02] The malformed-connection-string finding above (confirmed root cause
  of Fabric never having worked in any session to date) is added as **R-008**, cross-
  referenced with R-004 — a malformed string means every `.connect()` fails immediately,
  so R-004's pool-poisoning triggers on literally the first request.
- No visible distinction in `db.ts` between "Fabric mode was never configured" (silent
  SQLite fallback, by design) and "Fabric mode was configured but the connect failed"
  (permanent cache poisoning) from the caller's point of view — both eventually surface as
  errors/fallback behavior with no operator-facing signal distinguishing "never configured"
  from "configured and broken."

---

**IP-003 — Microsoft Fabric Lakehouse (`bronze`)**

Called by: M-008 (fabricLakehouse.ts)

What the application promises to send:
Parameterized `tedious` queries against `bronze.netsuite_vendorbill`/
`bronze.netsuite_vendorcredit`, scoped by `tranId`, `vendorNamePrefix`, and `amount` (no
input validation performed — passed straight through as query parameters). Read-only by
explicit design; no writes ever issued to this system. Auth is an AAD client-credentials
token, refreshed via `ClientSecretCredential`, obtained using `FABRIC_CLIENT_ID` /
`FABRIC_CLIENT_SECRET` / `FABRIC_TENANT_ID`, cached in-process until ~60s before expiry.

What the application assumes it will receive:
A `NetsuiteVendorBillRow` (`tranid`, `total`, `_run_id`, `_extracted_at`, `_source_system`,
`rawFields`) or `null`. `rawFields` is deliberately scoped to exclude the joined
`bronze.netsuite_vendor` entity's own columns (2026-09-01 decision) — fields outside that
shape are ignored. The app assumes vendor-scoped-then-amount-closest lookup is sufficient to
avoid `tranid` collisions across vendors (this fixed a real 2026-08-31 production
mismatching bug — re-adding an unscoped fallback would reopen it).

Auth mechanism:
[STAGE-2-DIVERGENCE - 2026-09-02] A03 states "NOT DETERMINABLE FROM SOURCE." `G08_fabricLakehouse.md`
fully determines this: AAD `ClientSecretCredential` (client-credentials OAuth flow) via the
three `FABRIC_CLIENT_*` env vars, token cached and refreshed proactively. Same staleness
pattern as IP-002 — this was determinable once Session G read the module, and was never
back-ported to A03.

Error handling assumptions:
[STAGE-2-DIVERGENCE - 2026-09-02] A03 states "NOT DETERMINABLE FROM SOURCE"; in fact nothing
in this module catches anything — `getAccessToken` throws explicitly on an empty token,
`tedious`'s connection `'error'` event and query-callback errors both reject the wrapping
Promise, and none of `findBillOrCreditRow`/`getReferenceRowByTranId`/`getCreditRowByTranId`/
`getLatestReferenceWatermark` catch any of it. Everything propagates to the sole caller,
M-026.

Known divergences:
- Auth/error-handling staleness, as above (same systemic cause noted under IP-002).
- IP-003 deliberately uses a **separate** env var (`FABRIC_LAKEHOUSE_SQL_ENDPOINT`) from
  IP-002's `FABRIC_SQL_ENDPOINT`, even though the module's own comment confirms both resolve
  to the same physical hostname. Nothing in A03's topology signals that these two "separate"
  integration points are, at the network level, the same Fabric workspace reached two
  different ways (`tedious` direct-connection here vs. `mssql` pool for IP-002) specifically
  to avoid tripping `getDbMode()` into Fabric app-state globally. A reader of A03 alone would
  not know consolidating these env vars is an explicitly-flagged landmine.

Gaps:
- **Uncaught-error cascade into the batch-abort issue**: because nothing in M-008 catches
  errors, a Fabric Lakehouse outage or auth failure propagates straight up through M-026 into
  M-025's per-document transaction (which discards all buffered work for that document on any
  exception) — and, if this happens during a scheduled batch run (IP-005), `runScheduledMatchingBatch`
  (M-017) has no per-document error isolation either (see IP-005 below and M-053's own
  contract), so a single Fabric Lakehouse hiccup mid-batch could abort every remaining
  eligible document in that run, not just the one line being checked. This specific
  cross-module cascade (IP-003 failure → IP-005 batch abort) does not appear to have been
  named anywhere else in the artifacts read this session.
- No connection pooling (a new `tedious` connection per query) — justified in-module by
  expected low call volume; flagged in `G08_fabricLakehouse.md` itself as a latent
  connection-storm risk under a future bulk/batch reconciliation flow, not yet realized.
- 60-second token-expiry safety margin depends on local clock accuracy relative to AAD's
  `expiresOnTimestamp` — no fallback if clock skew ever eats the margin.

---

**IP-004 — Microsoft Fabric Warehouse (`silver`, `gold`)**

Called by: M-003 (silver write path only); N/A for gold (no consuming or producing code
exists in this build — confirmed by Session A0's full codebase inventory per A01).

What the application promises to send:
Direct SQL `INSERT`s into `silver.statement_line` (one row per extracted line, INSERT-only —
S11/S6), issued through the **same** `mssql` `ConnectionPool`/singleton that IP-002 uses
(`M-003`'s `getFabricPool()` — there is only one Fabric connection pool in this codebase, not
one per logical schema). Not routed through `dbt`/`dbt-fabric` — confirmed absent from the
codebase's own call graph.

What the application assumes it will receive:
For `silver`: no read-back is assumed — M-024's INSERT-only design (S11) never re-reads what
it just wrote. For `gold`: nothing — no code path reads from `gold` anywhere in this build
(A01 confirms zero Gold/dbt-invoking files); this is a deliberate, documented scope decision
(Session 7 removed 2026-08-28/2026-09-01), not an unfinished implementation.

Auth mechanism:
NOT DETERMINABLE FROM SOURCE, and — unlike IP-002/IP-003 above — this is not really a
separate undetermined fact: IP-004's write path shares M-003's exact connection/pool with
IP-002, so whatever auth ambiguity applies to IP-002 applies identically here. A03 lists them
as five independent integration points; for IP-002/IP-004 specifically, they are the same
physical connection used for two logical schemas, not two independent auth surfaces.

Error handling assumptions:
NOT DETERMINABLE FROM SOURCE per A03, but functionally identical to IP-002's now-determined
behavior: the connection-pool permanent-cache bug (`R-004`) affects Fabric-mode writes into
`silver` exactly as it affects `recon` reads/writes, since both go through the same
`fabricPoolPromise` singleton. A Fabric connect failure at startup would silently break both
integration points simultaneously, not just one.

Known divergences:
- Same A03-staleness pattern as IP-002/IP-003.
- [STAGE-2-DIVERGENCE - 2026-09-02] A03 catalogues IP-002 and IP-004 as two separate
  integration points with independently-described directions/purposes. In reality, per
  `G03_db.md`, they share one connection-pool singleton — a failure in one is, by
  construction, a simultaneous failure in the other. Anyone using A03's "5 separate
  integration points" framing to reason about independent failure domains (e.g., for an
  incident-response runbook) would be wrong about IP-002/IP-004 specifically.

Gaps:
- `vendorSchema.ts` (M-041)'s Fabric DDL generation for per-vendor raw tables has no `IF NOT EXISTS`
  guard (unlike its SQLite counterpart) — calling it twice in Fabric mode would throw,
  contradicting its own "idempotent" doc comment. Currently unreachable (no code path
  exercises Fabric app-state for vendor-table creation in this build), so this sits latent
  under IP-004's schema-creation surface specifically — evaluated for the risk register (see
  RISK_REGISTER.md's "considered and not elevated" note) but judged not yet register-worthy
  given zero current trigger path.
- If Gold reporting integration is ever revived, there is no existing groundwork anywhere in
  this codebase to build from — not a defect, just worth naming so a future engineer doesn't
  assume partial plumbing exists.

---

**IP-005 — n8n**

Called by: M-053 (`api/matching/run-batch/route.ts`) — the receiving endpoint. Direction is
inbound: n8n is the caller here, not this application; M-053 is the sole handler.

What the application promises to send:
On success, a single 200 response with `{ processed: string[], skipped: string[] }` —
document IDs that were matched vs. document IDs whose lock was already held. **There is no
documented non-200 response from M-053 itself** — if any per-document `matchDocument()` call
inside M-017's `runScheduledMatchingBatch` throws (as opposed to finding a held lock), that
exception is not caught anywhere in the loop; it propagates out of the route handler entirely
and the framework returns an unhandled 500, with none of the batch's partial `processed`/
`skipped` progress included in that response. The 200-with-full-array contract the route
appears to promise does not hold under any single-document failure.

What the application assumes it will receive:
Nothing. `POST()` takes zero parameters; the request body is never read, never validated, and
no auth token/shared secret is checked inside the handler itself. Whatever n8n sends as a
request body is entirely ignored.

Auth mechanism:
[STAGE-2-DIVERGENCE - 2026-09-02] A03 states "NOT DETERMINABLE FROM SOURCE" for IP-005's
auth. Cross-reading M-053's own contract with M-043 (`proxy.ts`)'s auth matcher and
`INVARIANT_CATALOGUE.md`'s IC-CANDIDATE-03 makes this fully determinable, and the answer is
the most consequential finding in this session: `/api/matching/run-batch` is **not** excluded
from M-043's session-auth matcher the way `/api/health` (M-051) explicitly is. Every request
to M-053 — including n8n's — must carry a valid browser session cookie or `proxy.ts`
redirects it to `/login` before the route handler ever runs. n8n, as an external
machine-to-machine scheduler with no browser, has no documented way to obtain or present that
cookie. As coded, this is a session-cookie-authenticated endpoint masquerading as a
machine-to-machine trigger target.

Error handling assumptions:
The app's implicit assumption (per M-053's `{processed, skipped}` return shape) is
"per-document failures degrade gracefully into a skip/reprocess signal." The actual behavior
is the opposite for a true exception (as distinct from a lock contention, which does degrade
gracefully): one throwing document aborts the entire batch with zero partial-result
reporting, surfacing as an opaque 500 to n8n. Locks that were already acquired before the
throw are released via M-017's `finally`, so a retried batch is not blocked by stale locks —
but n8n has no visibility into which documents (if any) succeeded before the abort, since the
response body carrying that information is never sent.

Known divergences:
- [STAGE-2-DIVERGENCE - 2026-09-02] The auth mismatch above — this is exactly the
  cross-artifact inconsistency this session was asked to catch precisely: A03 (topology,
  Session A) describes IP-005 purely in terms of purpose and direction and leaves auth
  undetermined; `MODULE_CONTRACTS.md`'s M-053 row and `INVARIANT_CATALOGUE.md`'s
  IC-CANDIDATE-03 (Session D) both independently determined the same concrete fact — that the
  endpoint inherits session-cookie auth it structurally cannot satisfy — but neither of those
  findings was ever folded back into A03's own IP-005 entry, so a reader of TOPOLOGY.md alone
  still sees "NOT DETERMINABLE FROM SOURCE" for a fact two other sessions already settled.
- A03's stated purpose for IP-005 includes an **outbound** direction — n8n "sends completion
  notifications" after this app's work is done. No artifact read this session (including
  M-053's own contract, which is the module that would own any outbound call) shows this
  application making any outbound call to n8n; M-053 only returns a synchronous HTTP response
  to whatever called it. It's plausible n8n itself originates the notification after reading
  M-053's response (which would make A03's "sends" a description of n8n's own downstream
  behavior, not this app's), but nothing in the artifacts read this session confirms or rules
  this out — flagged as unresolved rather than asserted as a defect, since Session E does not
  read source directly.

Gaps:
- The auth mismatch is severe enough that it is promoted to the risk register as **R-006**,
  rather than left as a Gap only.
- Even a manual workaround (hand-provisioning a service-account session cookie into n8n's
  HTTP call) would be fragile beyond the auth-mismatch itself: M-043's session model uses a
  30-minute idle timeout (per its own Primary Responsibility). A monthly scheduled batch job
  is far outside that lifetime, so a hardcoded cookie would need to be refreshed before every
  single run by some process that isn't described as existing anywhere in the artifacts read.
- No idempotency key, rate limiting, or duplicate-trigger protection exists at the route
  level — protection against double-processing relies entirely on M-017's per-document lock,
  which is shared with M-047's manual Reconcile button (a race between the two is resolved
  safely — one gets skipped/409 — but this is incidental to the lock's original purpose, not
  a deliberate idempotency design for the n8n integration specifically).
- The whole-batch-abort-on-single-document-failure behavior (well-documented already in
  M-053/M-017's own contracts) means IP-005's practical reliability is only as good as the
  least-reliable document in any given batch — not flagged as a new register entry here since
  it is already fully captured at the module-contract level and the task's candidate list for
  Part 2 did not include it; noting it here for completeness since it directly affects this
  integration's real-world behavior.

---

## Cross-IP observation (not one IP's alone)

A03's Stage 2 pass (Session A) only fully updated IP-001's Auth/Error-handling fields (tagged
`[STAGE-2-UPDATE]`); IP-002 through IP-005 were left exactly as Stage 1 drafted them —
"NOT DETERMINABLE FROM SOURCE" across the board — even though later sessions (C for IP-001's
residual-matching caller, G for IP-002/IP-003, D for IP-005's auth) each independently
determined facts that belong in those fields. This isn't a contradiction in the sense of one
artifact asserting X and another asserting not-X; it's staleness — A03 simply was never
revisited once the information that would complete it came into existence elsewhere. Four of
the five `[STAGE-2-DIVERGENCE - 2026-09-02]` tags above stem from this one root cause. A
follow-up pass that back-ports the now-available Auth/Error-handling detail into A03 itself
(not just here) would remove the need to cross-reference this file to get a complete picture
of any single IP-NNN.
