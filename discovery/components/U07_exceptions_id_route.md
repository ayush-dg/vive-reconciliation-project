**Module:** api/exceptions/[id]/route.ts
**ID:** M-049
**Layer:** route
**Primary Responsibility:** Returns a single exception's full detail (GET) and applies the Mark-resolved/Flag-for-vendor/Skip resolution workflow with an optional note (PATCH), for the Exception Detail panel.

**Inputs:**
- `GET(_request: Request, { params }: { params: Promise<{ id: string }> })` — path param `id` (exception ID) only.
- `PATCH(request: Request, { params }: { params: Promise<{ id: string }> })` — path param `id`; body is JSON, parsed via `request.json().catch(() => ({}))` (so a malformed/absent JSON body degrades to `{}` rather than throwing). Expected body shape: `{ status?: string; note?: string }`. `status` is validated against `VALID_STATUSES = ['open','resolved','flagged','skipped']`; `note` is passed through unvalidated (optional).
**Outputs:**
- `GET` 200: `ExceptionDetailData` — `{ exceptionId, category, status, note, resolvedAt, createdAt, referenceExtractedAt, statementLine: {lineId,invoiceRef,amount,documentId,vendorSlug,statementPeriod}, cccCorroboration: {roNumber,amount}|null, amountMismatch: {statementAmount,netsuiteAmount}|null, netsuiteRecord: Record<string,unknown>|null }` (per M-018).
- `GET` 404: `{ error: 'Exception not found.' }` when `getExceptionDetail(id)` returns `null`.
- `PATCH` 400: `{ error: 'status must be one of open, resolved, flagged, skipped.' }` when `body.status` is missing or not one of `VALID_STATUSES`.
- `PATCH` 404: `{ error: err.message }` (or `'Update failed.'` if the caught error is not an `Error` instance) — thrown by `updateExceptionResolution` (M-018) when `result.changes === 0`, i.e. no exception row matches `id`.
- `PATCH` 200 (on success): re-fetches and returns the full `ExceptionDetailData` via a second call to `getExceptionDetail(id)` — the same shape as `GET`'s 200. Note: `updateExceptionResolution` itself returns `void`; the PATCH response is entirely a fresh read-after-write, not the write result echoed back.
**Public Interface:**
`export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }): Promise<NextResponse>`
`export async function PATCH(request: Request, { params }: { params: Promise<{ id: string }> }): Promise<NextResponse>`
**Error Behaviour:** `GET` has no try/catch — any M-018 exception (e.g. non-SQLite mode) is unhandled -> 500. `PATCH` wraps only the `updateExceptionResolution` call in try/catch, converting any thrown error to a 404 (not a 500) — this means a genuine DB connectivity error inside `updateExceptionResolution` would be misreported to the client as "exception not found" rather than a server error, since the catch does not distinguish "no matching row" from other failure modes. The re-fetch (`getExceptionDetail`) after a successful PATCH is NOT inside the try/catch, so if it throws, that IS unhandled -> 500 despite the write having already succeeded (client sees a 500 for what was actually a successful update).
**Known Fragility:** [NOTABLE] `updateExceptionResolution` (M-018) is documented as an explicit, engineer-directed deviation from `ARCHITECTURE.md` D-C, which states "this build's exceptions are a flat, ownerless list by design — no review/approval workspace." This PATCH endpoint's entire resolution workflow (status/note/resolvedAt) exists outside that documented architecture. A future engineer reconciling this route against `ARCHITECTURE.md` alone would conclude it shouldn't exist. The malformed-JSON-body fallback (`.catch(() => ({}))`) means any parse failure silently becomes "no status provided" -> 400, not a distinguishable parse-error response. `resolvedAt` is set to `null` if `status === 'open'` and to `new Date().toISOString()` otherwise (server clock, not client-supplied) — reopening an exception (PATCH to `'open'`) clears `resolvedAt` even if it was previously resolved.
**Change Impact:** Sole data+action source for the Exception Vendor Detail two-pane view (M-074), which calls both GET and PATCH and depends on PATCH returning the full refreshed detail object (not just an ack) to update its UI in place. Changing `VALID_STATUSES` changes what M-074's Mark resolved/Flag/Skip actions can send. The PATCH-returns-GET-shape convention means any change to `ExceptionDetailData` (M-018) affects both handlers identically.
**Callers:** M-074 (ExceptionVendorDetailView.tsx, fetch GET+PATCH)
**Calls:** M-018 (`src/app/api/exceptions/[id]/route.ts:9,30,35`)
**Integration Points Used:** None (routes through serving-layer modules)
