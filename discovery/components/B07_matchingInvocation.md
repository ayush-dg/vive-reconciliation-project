**Module:** matchingInvocation.ts
**ID:** M-017
**Layer:** serving
**Primary Responsibility:** Matching invocation entry points — manual per-document (Reconcile button) and scheduled batch — with G5 lock acquisition/release wrapped around the shared matching-pipeline execution.

**Inputs:**
- `acquireMatchingLock(documentId: string): boolean`
- `releaseMatchingLock(documentId: string): void`
- `triggerMatchingForDocument(documentId: string): Promise<TriggerMatchingResult>`
- `runScheduledMatchingBatch(): Promise<ScheduledMatchingBatchResult>` — no parameters; internally discovers eligible document ids (lines with neither a match nor an exception yet).

**Outputs:** Side effect: atomic UPSERT into `recon_document_lock` on acquire (`INSERT ... ON CONFLICT DO UPDATE ... WHERE acquired_at < stale-threshold`); `DELETE` from `recon_document_lock` on release. Triggers `runMatchingForDocument` (M-025), which performs its own further downstream writes (matches/exceptions), not owned by this module. Exports `LOCK_STALE_AFTER_MINUTES = 10` as a shared constant, directly consumed by M-012 as a data-reference (not a call). Returns `TriggerMatchingResult` / `ScheduledMatchingBatchResult`.

**Public Interface:**
- `export const LOCK_STALE_AFTER_MINUTES = 10`
- `export function acquireMatchingLock(documentId: string): boolean`
- `export function releaseMatchingLock(documentId: string): void`
- `export type TriggerMatchingResult = { ok: true } | { ok: false; reason: 'not_found' | 'already_processing' }`
- `export async function triggerMatchingForDocument(documentId: string): Promise<TriggerMatchingResult>`
- `export type ScheduledMatchingBatchResult = { processed: string[]; skipped: string[] }`
- `export async function runScheduledMatchingBatch(): Promise<ScheduledMatchingBatchResult>`

**Error Behaviour:**
- `triggerMatchingForDocument`: wraps `await matchDocument(documentId)` in try/**finally** (not try/catch) — `releaseMatchingLock` always runs, so the lock itself is never left stuck on a pipeline failure (unlike M-015's extraction lock). But any exception thrown by `matchDocument` (M-025) is NOT caught here — it still propagates uncaught to the caller (M-047) after the finally block releases the lock.
- `runScheduledMatchingBatch`: same try/finally-per-document pattern inside its loop. [NOTABLE] An exception from `matchDocument` for one document is not caught — it propagates out of `runScheduledMatchingBatch` entirely, aborting the batch for all remaining documents (the lock for the failing document is still released via finally, but no partial `{processed, skipped}` result is ever returned in that case — the function throws instead).
- `acquireMatchingLock`/`releaseMatchingLock`: no try/catch; a DB error propagates uncaught.

**Known Fragility:**
- [NOTABLE] No per-document error isolation in `runScheduledMatchingBatch` — a single throwing `matchDocument` call aborts the entire batch loop, losing the "processed so far" list entirely. A future engineer might assume from `ScheduledMatchingBatchResult`'s shape that failures are captured in the result — they are not; only lock contention (`skipped`) is captured there, not pipeline failures.
- The staleness-reclaim SQL in `acquireMatchingLock` means a lock can be silently "stolen" by a second caller once `LOCK_STALE_AFTER_MINUTES` elapses even if the original run is still legitimately in progress (e.g. a slow Fabric lookup) — an accepted tradeoff against hard-crash-abandoned locks, but a real correctness risk if any real matching run can legitimately exceed 10 minutes.
- `LOCK_STALE_AFTER_MINUTES` is imported directly as a value by M-012 to independently compute the same staleness window for its "Reconciling" badge check — a data-reference dependency invisible in the call graph; changing this constant here silently changes M-012's badge behavior too.

**Change Impact:** M-047 (manual Reconcile button route) and M-053 (scheduled/external-trigger batch endpoint) are the two direct callers. M-012 is a silent data-dependent consumer of `LOCK_STALE_AFTER_MINUTES`. A change to the lock schema, staleness constant, or `TriggerMatchingResult`/`ScheduledMatchingBatchResult` shapes cascades to the Reconcile button UI (M-076/M-068) and to the Reconciling badge path (M-012 → M-011/M-013 → multiple screens).

**Callers:** M-047, M-053
**Calls:** M-003, M-025
**Integration Points Used:** None (routes through M-003)

**Data-reference (non-call) dependency:** `LOCK_STALE_AFTER_MINUTES` is read directly by M-012 as a shared constant value — not a function call.
