**Module:** extractionPipeline
**ID:** M-022
**Layer:** pipeline
**Primary Responsibility:** Orchestrates the full extraction flow for one document — vendor identification/routing, attempt recording (always, before any retry decision), the bounded 2-attempt retry loop, and Silver normalization on success.

**Inputs:**
- `documentId: string` — must exist in `extracted_document` (looked up for `content_sha256`/`legal_entity_id`); throws if not found.
- Reads `extracted_extraction_attempt` (count of existing attempts, and the latest attempt's pass flags for the idempotency guard).
- Reads the document's PDF bytes via `readDocumentFile(document.content_sha256)` (M-005/storage.ts).
- SQLite-only (`assertSqliteMode()`).

**Outputs:**
- No return value (`Promise<void>`) — all results are side effects.
- `INSERT INTO extracted_extraction_attempt` unconditionally, once per attempt, BEFORE any retry decision (S10/G1) — including on catastrophic failure (subprocess spawn error, missing file).
- `INSERT INTO ${vendor.tableName}` (raw per-vendor row) only when `provider === 'python_library_pdfplumber' && vendor` is truthy.
- Calls `normalizeToSilver` (M-024) on a passing attempt, writing `silver_statement_line` rows.
- No `document.status` mutation — status is derived elsewhere (Task 2.3) purely from attempt history.

**Public Interface:**
- `export async function runExtractionPipeline(documentId: string): Promise<void>`
- `export const MAX_ATTEMPTS = 2` (not exported — module-local `const`, S7's bound)

**Error Behaviour:**
- `document` not found: throws synchronously (`Error(`runExtractionPipeline: document ${documentId} not found.`)`) — uncaught, propagates to the caller (extraction trigger, Task 2.4).
- `hasAlreadySucceeded`: returns early (no-op) if the latest attempt already has `arithmetic_pass=1 AND structural_pass=1` — an idempotency guard, not error handling; explicitly documented as NOT bulletproof (no DB uniqueness constraint prevents a concurrent/direct call from double-writing).
- Per-attempt: `identifyAndExtract` (and everything it calls — pdfplumber subprocess, Claude API, known-vendor extractors) is wrapped in try/catch; ANY exception during the attempt is caught and recorded as `rawOutput = "attempt failed before extraction outcome was available: <message>"`, with `provider = null`, `arithmeticPass = false`, `structuralPass = false` — the attempt row is still written (S10 requirement), then the loop proceeds to the next attempt or exits at `MAX_ATTEMPTS`. **The caller never sees this exception** — it's fully swallowed at the attempt level.
- Silver normalization failure (`normalizeToSilver` throws) on an attempt that PASSED validation: caught and RE-THROWN with added context (`"...passed validation on attempt ${attemptNo} but Silver normalization failed: ..."`) — this is the one path where the function itself throws out to its caller, deliberately not swallowed, since the attempt row (correctly showing pass) is already committed and an unhandled rejection here would have no diagnostic trail.
- At `MAX_ATTEMPTS` with no success: returns silently (no throw, no explicit "failed" write) — downstream status derivation reads this as "Failed — see Exceptions" from attempt history alone.

**Known Fragility:**
- The task description flags a live-run S7 finding: "a bounded-retry success doesn't update the status badge correctly." Reading this module's retry logic: `runExtractionPipeline` deliberately does NOT touch `document.status` on success or failure — the comment at line ~162 states status is derived purely from attempt history by a separate module (Task 2.3's status computation, believed to be M-012 per the task brief). **This module's own contract is consistent** (it correctly writes `arithmetic_pass`/`structural_pass` per attempt and returns immediately on first success without any further writes) — nothing here appears to fail to signal success. If the badge doesn't update on a bounded-retry success, the bug is downstream in whatever reads `extracted_extraction_attempt` to compute the badge (M-012, per the task brief, not this module) — possibly a stale-read or an off-by-one in "which attempt counts as latest" there, not in this module's write path.
- `routeNextAttemptToFallback` is set `true` ONLY when `provider === 'claude_sonnet' && extracted === null` — a validation-only failure (extracted present but arithmetic/structural failed) retries the exact same path unchanged. A future engineer "fixing" retries to always escalate to fallback would silently change cost/behavior for the common validation-failure case, which this code explicitly preserves as unchanged.
- The raw per-vendor row write (`INSERT INTO ${vendor.tableName}`) uses string interpolation of `vendor.tableName` directly into SQL — relies entirely on `vendorSchema.ts`'s slug validation (`assertValidVendorSlug`) upstream to prevent injection; this module does not itself re-validate `tableName`.
- `getExistingAttemptCount` and `hasAlreadySucceeded` both run as separate un-transactioned reads before the loop starts — a genuinely concurrent second call to `runExtractionPipeline` for the same document (bypassing whatever external lock, e.g. G5, is supposed to prevent it) could both pass the idempotency check and double-process, exactly as the module's own comment (lines 39–44) warns.

**Change Impact:** Any change to `ExtractedStatement`/`ExtractionOutcome` shape (M-028) or `VendorRegistryRow` (M-021) breaks this orchestrator's destructuring. Changing `MAX_ATTEMPTS` changes S7's documented bound system-wide. This is the sole caller of `identifyAndExtract`, `validateExtraction`, and `normalizeToSilver` — breaking any of those three signatures breaks this module directly.

**Callers:** M-015 (line 49, per the internal call table — extraction.ts's Extract trigger)
**Calls:** M-003 (26,32,46,58), M-005 (97), M-021 (98), M-023 (106), M-024 (147)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
