**Module:** aiProvider
**ID:** M-028
**Layer:** pipeline
**Primary Responsibility:** Claude Sonnet vendor-statement extraction ("Claude-primary" path) — routes between two live paths (Azure AI Foundry, direct Anthropic API) and a deterministic marker-based mock, depending on env configuration and explicit test opt-in.

**Inputs:**
- `extractViaClaude(pdfBytes: Buffer, pdfText: string)` — raw PDF bytes for a real call, plus the pre-extracted text layer for the mock path (which does no PDF parsing of its own).
- Env vars: `AZURE_CLAUDE_API_KEY`, `AZURE_CLAUDE_ENDPOINT`, `AZURE_CLAUDE_SONNET_DEPLOYMENT` (Azure Foundry path); `ANTHROPIC_API_KEY` (direct path); `EXTRACTION_LIVE_TESTS` (must be exactly `'1'` to opt into either live path).

**Outputs:**
- Returns `ExtractionOutcome` — no DB writes, no other side effects (pure request/response mapping). All persistence happens in the caller (`vendorIdentification.ts` / `extractionPipeline.ts`).

**Public Interface:**
- `export async function extractViaClaude(pdfBytes: Buffer, pdfText: string): Promise<ExtractionOutcome>`
- `export function shouldUseLiveExtraction(): boolean`
- `export function shouldUseAzureFoundryExtraction(): boolean`
- `export const CLAUDE_MODEL_ID = 'claude-sonnet-5'`
- `export const EXTRACTION_SYSTEM_PROMPT = "..."` — exported for a structural G3 byte-identity test.
- `export type ExtractedLine`, `export type ExtractedStatement`, `export type ExtractionOutcome`

**Error Behaviour:**
- Neither live path (`extractViaClaudeLive`, `extractViaAzureFoundryClaude`) catches anything — an API error, timeout, or auth failure propagates uncaught to the caller (`vendorIdentification.ts`, M-021, which itself does not catch it either — propagates further to `extractionPipeline.ts`'s per-attempt try/catch, M-022).
- `parseRecordExtractionResponse`, however, degrades gracefully (does NOT throw) for two documented failure shapes that were previously ungated crashes: (1) `response.stop_reason === 'max_tokens'` — a statement with enough line items can exceed the token budget mid-tool-call, before the `lines` array finishes writing; returns `extracted: null` with a `[truncated: ...]`-tagged `rawOutput` rather than letting `input.lines.map()` crash on a malformed partial object. (2) `tool_use.input` present but `!Array.isArray(input.lines)` — defensive even with the `stop_reason` guard, same degrade-to-`null` pattern.
- `extractViaAzureFoundryClaude` uses non-null assertions (`process.env.AZURE_CLAUDE_ENDPOINT!`, `AZURE_CLAUDE_API_KEY`, `AZURE_CLAUDE_SONNET_DEPLOYMENT!`) — only reachable when `shouldUseAzureFoundryExtraction()` already confirmed `AZURE_CLAUDE_API_KEY` is set, but `AZURE_CLAUDE_ENDPOINT`/`AZURE_CLAUDE_SONNET_DEPLOYMENT` are NOT checked by that gate function — if either of those two is unset while `AZURE_CLAUDE_API_KEY` and `EXTRACTION_LIVE_TESTS=1` are both set, `new URL(undefined!)` or a `model: undefined!` throws at call time, not at the gate check.

**Known Fragility:**
- [historical bug, fixed] `max_tokens` was raised from 4096 to 16000 (2026-09-01) specifically because Fred Beans/Astech both crashed identically on 2 straight attempts at the old limit, downstream at `input.lines.map()`. The `stop_reason === 'max_tokens'` guard in `parseRecordExtractionResponse` is the actual fix; the token bump alone reduces frequency but does not eliminate the failure mode — any future statement with even more line items than 16000 tokens accommodates will hit the same guard again (correctly, by design) rather than crash.
- `resource` in `extractViaAzureFoundryClaude` is derived by parsing `AZURE_CLAUDE_ENDPOINT` as a URL and taking only the hostname's first dot-segment — the module's own comment states passing the FULL hostname instead (a plausible-looking mistake) doubles Azure Foundry's own suffix and fails DNS resolution. A future engineer copy-pasting the full endpoint URL into this env var (instead of just the resource name) would get an opaque DNS failure, not a clear config error.
- `model` for the Azure Foundry path must be the Azure DEPLOYMENT NAME, not a raw Anthropic model ID — the module's own comment notes `AZURE_CLAUDE_DEPLOYMENT` ("claude-haiku-4-5") does NOT exist in this Azure resource (confirmed 404) and only the Sonnet deployment is actually provisioned; a future engineer adding a Haiku-based fast path by reusing that env var name would hit a 404 at runtime, not a config-time check.
- `shouldUseLiveExtraction()`/`shouldUseAzureFoundryExtraction()` require BOTH a key AND `EXTRACTION_LIVE_TESTS === '1'` — a key alone is never enough. This same toggle is shared with `aiResidualMatching.ts` (M-027) via `shouldUseLiveExtraction` — see M-027's fragility note on this shared gate.
- Azure Foundry is checked BEFORE the direct Anthropic path in `extractViaClaude` — order-dependent; if both are ever configured simultaneously, Azure always wins silently.

**Change Impact:** `ExtractedStatement`/`ExtractedLine`/`ExtractionOutcome` are the shared extraction data contract consumed by `vendorIdentification.ts` (M-021), `extractionPipeline.ts` (M-022), `validationGate.ts` (M-023), `silverNormalization.ts` (M-024), `pdfplumberExtractor.ts` (M-029), `pdfplumberOcrFallback.ts` (M-030), and all 9 vendor wrappers (M-032–M-040) — this is the single most widely-depended-on type definition in the pipeline layer; any field rename ripples through nearly every module in this set. `CLAUDE_MODEL_ID` is also read (not called) by `aiResidualMatching.ts` (M-027).

**Callers:** M-021 (230), M-027 (132, data-reference to `CLAUDE_MODEL_ID` — not a Calls edge)
**Calls:** none listed in the internal call table (external SDK calls to Anthropic/Azure Foundry only)
**Integration Points Used:** IP-001 (Claude/Anthropic via Azure AI Foundry)
