**Module:** aiResidualMatching
**ID:** M-027
**Layer:** pipeline
**Primary Responsibility:** For a deterministically-unmatched Silver line, proposes a human-actionable next step using CCC repair-order data as corroborating evidence — never resolves or auto-approves a match itself (proposal-only, `status: 'proposed'` always).

**Inputs:**
- `runResidualMatch(line: { normalizedInvoiceRef: string | null; amount: number })` — the unmatched line's key fields.
- Reads `bronze_ccc_repair_order` (SQLite; wrapped in try/catch since the table name is an unconfirmed placeholder, not a verified production name).
- Reads `CLAUDE_MODEL_ID` constant from `aiProvider.ts` (M-028) — a value read, not a call.

**Outputs:**
- Returns `ResidualMatchOutcome` — `status: 'proposed'` unconditionally, `requiresReview: true` unconditionally (typed as the literal `true`, not `boolean`, so this can never structurally be set to `false`).
- No DB writes at all — this module never writes `recon.match` or any other table. The only channel to `recon.match` remains `deterministicMatching.ts`'s `writeMatch` (M-026), which this module never calls.

**Public Interface:**
- `export async function runResidualMatch(line: { normalizedInvoiceRef: string | null; amount: number }): Promise<ResidualMatchOutcome>`
- `export type ResidualMatchOutcome = { stage: 'ai_residual_match'; status: 'proposed'; candidateIds: string[]; reasonCodes: string[]; evidence: Record<string, unknown>; confidence: number | null; requiresReview: true }`
- `export type CccCorroboration = { roNumber: string; amount: number; runId: string; extractedAt: string; sourceSystem: string }`
- `export const RESIDUAL_SYSTEM_PROMPT = "..."` — exported specifically so a G3 structural test can assert byte-identity against the live API call.

**Error Behaviour:**
- `findCccCorroboration`: wraps its query in try/catch. ANY query failure — including the EXPECTED "table doesn't exist under this placeholder name" case AND a genuine schema/query bug — is caught, logged via `console.error`, and degraded to `null` (no corroboration). The module's own comment explicitly flags this as intentional (can't tell the two failure modes apart from inside the catch, so it logs to keep a real bug visible without changing the degrade-gracefully behavior). A future engineer silently removing the `console.error` (thinking it's noise, since the "table missing" case is expected and constant) would make a genuine future schema bug invisible.
- `proposeActionViaClaudeLive`: no try/catch around the `client.messages.create` call — an Anthropic API error (rate limit, network, auth) propagates uncaught to `runResidualMatch`'s caller (`matchingPipeline.ts`, M-025), which itself does not catch it either (see M-025's all-or-nothing fragility).
- If the live call returns no `tool_use` block, degrades gracefully to a fixed string (`'No suggestion available — model did not return a proposal.'`) rather than throwing.

**Known Fragility:**
- `shouldUseLiveExtraction()` (imported from `aiProvider.ts`, M-028) gates BOTH the extraction path's live-vs-mock choice AND this module's live-vs-mock choice — a single shared toggle. A future engineer wanting extraction to go live while residual matching stays mocked (or vice versa) would find no way to do so without adding a new, separately-named env-gate function; this module has no distinct opt-in of its own.
- The CCC table name (`bronze_ccc_repair_order`) is explicitly documented as this project's OWN placeholder, not a confirmed production name (unlike `bronze.netsuite_vendorbill`, which M-026 confirmed by direct Lakehouse inspection) — a future engineer wiring this against live Fabric data would need to first confirm the real CCC table name; nothing here validates that assumption.
- `findCccCorroboration`'s tolerance window uses the SAME `AMOUNT_TOLERANCE = 0.01` constant name as `deterministicMatching.ts`, again independently defined (not shared) — see M-026's note on the same pattern.
- The residual pass runs unconditionally for every unmatched line in `matchingPipeline.ts` (M-025), including lines with no invoice ref at all (`NOT_POSTED` with `normalizedInvoiceRef: null`) — `findCccCorroboration` still runs a real query in that case (scoped only by amount), and the live-Claude path (when enabled) still makes a real API call passing `normalized_invoice_ref: null` — no short-circuit for "definitely nothing useful to corroborate here."

**Change Impact:** `matchingPipeline.ts` (M-025) is the sole caller and merges this module's `reasonCodes`/`evidence` into the exception it writes — renaming a reason code (`CCC_CORROBORATED`/`NO_CCC_CORROBORATION`) here is a silent contract change for any downstream code inspecting exception reason codes. Depends on `aiProvider.ts`'s `CLAUDE_MODEL_ID` and `shouldUseLiveExtraction` — a rename or removal of either breaks this module at compile time (both are named imports).

**Callers:** M-025
**Calls:** M-003 (36), M-028 (132)
**Integration Points Used:** None (routes through M-003 or another pipeline module). [NOTABLE] This module also reads `CLAUDE_MODEL_ID` from M-028 (a data reference, not a Calls edge) and, in `proposeActionViaClaudeLive`, constructs its own `new Anthropic()` client and sends its own `messages.create` request directly — in effect a second, independent direct-to-IP-001 call site in the codebase, distinct from M-028's own extraction call. Per this contract's IP-NNN attribution, IP-001 is recorded against M-028 as the module of record; a future engineer auditing every place the Anthropic API is actually invoked from should be aware this module is one such place too, not just a consumer of M-028's constant.
