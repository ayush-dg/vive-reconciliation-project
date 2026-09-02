**Module:** matchingPipeline
**ID:** M-025
**Layer:** pipeline
**Primary Responsibility:** Orchestrates per-document matching — deterministic match first per line, residual AI corroboration for unmatched lines, then writes all `recon.match`/`recon.exception` rows for the document together in a single transaction at the end.

**Inputs:**
- `documentId: string` — the sole parameter to `runMatchingForDocument`.
- Reads eligible lines via `getEligibleLinesForDocument`: `silver_statement_line` LEFT JOINed to `extracted_vendor_registry` (for `vendorSlug`), filtered to lines with no existing `recon_match` or `recon_exception` row (idempotent re-run safe at the per-line level).
- SQLite-only (`assertSqliteMode()`).

**Outputs:**
- No return value (`Promise<void>`).
- Buffers all per-line outcomes in memory (`pending: PendingWrite[]`) during the async loop, then commits everything in ONE synchronous `db.transaction` at the end — deliberately re-ordered (2026-08-31, engineer-directed) from the prior per-line-commit design specifically so a concurrent reader (Exceptions screen, Home stats) never observes a partially-processed document.
- Side effect: `writeMatch` (M-026) for each resolved line; `writeException` (exceptionWriter, not in this module set) for each unresolved line.

**Public Interface:**
- `export async function runMatchingForDocument(documentId: string): Promise<void>`

**Error Behaviour:**
- `assertSqliteMode()` throws synchronously if not SQLite.
- If a line's deterministic outcome is `status: 'matched'` but has no `reference` object, throws synchronously (`Error("runMatchingForDocument: matched outcome for line ${line.lineId} had no reference capture.")`) — this is a defensive invariant check against `deterministicMatching.ts`'s own contract (every matched outcome must carry a reference); not expected to be reachable in practice, but not caught here — propagates uncaught to the caller.
- Any exception thrown by `matchStatementLine` or `runResidualMatch` (e.g. a Fabric network error, a Claude API error) is NOT caught anywhere in this module — propagates uncaught, meaning the entire buffered `pending` array for the document (including any lines already successfully processed earlier in the same loop) is discarded, and NOTHING is committed. This is a real all-or-nothing failure mode: if line 50 of 100 throws, the first 49 lines' matching work is silently lost (not written, not retried, no partial commit) — the caller must invoke `runMatchingForDocument` again for the whole document, re-doing all 49.

**Known Fragility:**
- The write-ordering change (buffer-then-commit) trades atomicity/visibility correctness for all-or-nothing failure blast radius — before this change, a mid-loop exception would have left partial matches already committed and only failed on the remaining lines; now it leaves NOTHING committed. A future engineer investigating "why did a document with 100 lines produce zero matches after a Fabric timeout on line 50" needs to know this deliberate tradeoff exists.
- `getEligibleLinesForDocument`'s `NOT EXISTS` filters make a full document reprocess after a partial failure naturally skip nothing already committed — but combined with the above, a genuinely partial-failure document (transaction rolled back, so nothing committed) is NOT actually partially eligible on retry; the entire document reprocesses from scratch, redoing every network round-trip (Fabric lookups, Claude residual calls) even for lines that succeeded before the exception.
- Category classification (`amount_mismatch` vs `not_posted`) is derived by checking `outcome.reasonCodes.includes('AMOUNT_MISMATCH')` — a bare string-literal check against `deterministicMatching.ts`'s reason codes; renaming that reason code in M-026 silently breaks this categorization with no compile-time error.
- The residual match pass (`runResidualMatch`, M-027) runs for EVERY unmatched line unconditionally (including `NOT_POSTED` lines with no invoice ref at all) — each such call is a real network/DB round-trip (CCC lookup, possibly a live Claude call), so a document with many unmatched lines multiplies cost/latency here even when corroboration is unlikely to help.

**Change Impact:** Both `deterministicMatching.ts` (M-026) and `aiResidualMatching.ts` (M-027)'s output shapes (`MatchOutcome`, `ResidualMatchOutcome`) are directly destructured here — changing either's field names breaks this orchestrator. The buffered-write transaction is the single point where `recon_match`/`recon_exception` visibility is controlled system-wide for a document; any future per-line-commit "optimization" would reintroduce the exact partial-visibility bug this design fixed.

**Callers:** M-017 (per the internal call table)
**Calls:** M-003 (32,40,94), M-026 (69,97), M-027 (79), M-020 (98)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
