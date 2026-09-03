**Module:** exceptionDetail.ts
**ID:** M-018
**Layer:** serving
**Primary Responsibility:** Reads a single exception's full detail — including CCC corroboration and amount-mismatch evidence parsed out of the stored JSON evidence blob — and is the sole write path for updating an exception's resolution status.

**Inputs:**
- `getExceptionDetail(exceptionId: string): ExceptionDetailData | null`
- `updateExceptionResolution(exceptionId: string, input: { status: ExceptionStatus; note?: string | null }): void` — `status` must be one of `'open'|'resolved'|'flagged'|'skipped'` (`VALID_STATUSES`), runtime-checked; `note` is optional.

**Outputs:** `getExceptionDetail` is read-only. `updateExceptionResolution` performs `UPDATE recon_exception SET status = ?, note = COALESCE(?, note), resolved_at = ? WHERE exception_id = ?` — `resolved_at` is set to the current timestamp unless `status === 'open'`, in which case it is cleared to `null`.

**Public Interface:**
- `export type CccEvidence = { roNumber: string; amount: number } | null`
- `export type AmountMismatchEvidence = { statementAmount: number; netsuiteAmount: number } | null`
- `export type ExceptionStatus = 'open' | 'resolved' | 'flagged' | 'skipped'`
- `export type ExceptionDetailData`
- `export function getExceptionDetail(exceptionId: string): ExceptionDetailData | null`
- `export function updateExceptionResolution(exceptionId: string, input: { status: ExceptionStatus; note?: string | null }): void`

**Error Behaviour:** `getExceptionDetail` has no try/catch except explicitly around `JSON.parse(row.evidence)` — a malformed evidence JSON string is caught and degrades to an empty `{}` object (silently — "no evidence shown," not a crash) rather than propagating. The guard specifically checks `if (row.evidence)` truthy first, because `JSON.parse(null)` returns JS `null` without throwing and would bypass the catch — a NULL evidence column is explicitly handled outside the try/catch, not accidentally relying on it. `updateExceptionResolution` throws uncaught if `input.status` is not in `VALID_STATUSES` (defense-in-depth ahead of the DB's own CHECK constraint), and throws uncaught if `result.changes === 0` (no row matched `exceptionId`) — deliberate fail-loud rather than a silent no-op PATCH.

**Known Fragility:**
- The evidence JSON schema (`evidence.residual.cccCorroboration`, `evidence.deterministic.{statementAmount,netsuiteAmount,netsuiteRecord}`) is entirely implicit/untyped — this module uses `as` type assertions with no runtime schema validation beyond the outer `JSON.parse` try/catch. A producer (M-026 deterministic matching, M-027 AI residual matching) writing evidence in a slightly different shape would not error here — the corresponding field would simply come back `null`/`undefined` with no error signal anywhere.
- `amountMismatch` is additionally gated on `row.category === 'amount_mismatch'` — a future engineer changing category values without updating this string-literal check would silently break the gate.
- `updateExceptionResolution`'s `note` uses `COALESCE(?, note)` — passing `note: null` explicitly is indistinguishable from omitting `note` entirely (both leave the existing note unchanged). There is no way via this function's public interface to explicitly clear a note back to `null`; a future caller expecting `note: null` to clear it will be surprised.

**Change Impact:** M-049 is the sole caller for both GET (detail) and PATCH (resolution) — the Exception Detail two-pane view (M-074) depends entirely on this module via that one route for both viewing and the Mark resolved/Flag for vendor/Skip actions.

**Callers:** M-049
**Calls:** M-003
**Integration Points Used:** None (routes through M-003)
