**Module:** api/documents/[id]/detail/route.ts
**ID:** M-045
**Layer:** route
**Primary Responsibility:** Returns a single document's full detail payload (header info, status badge, extraction-method summary, extracted statement lines, and line-level reconciliation counts) for the Document Detail screen's data/refresh endpoint.

**Inputs:** `GET(_request: Request, { params }: { params: Promise<{ id: string }> })` — path param `id` (document ID), awaited from the Next.js 15 async `params`. No query params, no body (the leading `_request` parameter is unused).
**Outputs:**
- 200: `DocumentDetailData` — `{ documentId, vendorSlug: string|null, statementPeriod: string|null, status: string, statusBadge: {badge,label}, extractionMethodSummary: Record<string,number>, lines: StatementLineRow[], reconciliation: {totalLines,matchedLines,exceptionLines} }`. Each `StatementLineRow`: `{ lineId, invoiceRef: string|null, amount: number, confidence: number|null, providerUsed: string|null }`.
- 404: `{ error: 'Document not found.' }` when `getDocumentDetail(id)` returns `null` (i.e. `getDocumentById` in M-011 finds no row for that ID).
**Public Interface:**
`export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }): Promise<NextResponse>`
**Error Behaviour:** No try/catch in the handler. The only explicit branch is the null-detail 404. Any thrown error from `getDocumentDetail` (M-013) — e.g. Fabric mode (`assertSqliteMode()` throws if `getDbMode() !== 'sqlite'`), or a DB connectivity failure — is unhandled here -> Next.js default 500.
**Known Fragility:** `reconciliation.matchedLines`/`exceptionLines` are documented (in M-013) as expected to be either both 0 (matching never ran) or sum to `totalLines` (matching commits atomically per document) — this route has no defensive check enforcing that invariant; a partial/inconsistent DB state (e.g. manual data edit, crash mid-transaction outside the documented atomic commit path) would be surfaced to the UI as-is with no validation. `extractionMethodSummary` shape (`Record<string,number>`) is entirely dependent on M-016's output — no schema enforced at this layer.
**Change Impact:** Sole data source for the Document Detail screen's initial load and its post-action refresh (called again after Extract/Reconcile completes, per this route's own doc comment) — M-076 (DocumentDetailView.tsx). A change to `DocumentDetailData`'s shape (M-013) propagates directly into M-076's rendering without any transformation in this route.
**Callers:** M-076 (DocumentDetailView.tsx, fetch)
**Calls:** M-013 (`src/app/api/documents/[id]/detail/route.ts:9`)
**Integration Points Used:** None (routes through serving-layer modules)
