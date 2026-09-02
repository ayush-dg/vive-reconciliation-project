**Module:** api/home-summary/route.ts
**ID:** M-052
**Layer:** route
**Primary Responsibility:** Returns the Home screen's aggregate summary statistics (documents processed, open exceptions, reconciled/not-reconciled counts) as that screen's refresh endpoint.

**Inputs:** `GET()` — no params, no query, no body.
**Outputs:** 200 only: `HomeSummaryStats` — `{ documentsProcessed: number, openExceptions: number, reconciledCount: number, notReconciledCount: number }` (per M-014's `getHomeSummaryStats()`). No non-200 path in this handler.
**Public Interface:**
`export async function GET(): Promise<NextResponse>`
**Error Behaviour:** No try/catch. Any exception from `getHomeSummaryStats()` (M-014) — e.g. non-SQLite mode via `assertSqliteMode()`, or a DB error mid-aggregate-query — is unhandled -> Next.js default 500.
**Known Fragility:** `reconciledCount` is a line-level count (`recon_match` row count) while `notReconciledCount` is document-level (`documents.length - fullyReconciledDocs`, where `fullyReconciledDocs` counts documents whose status badge is exactly `'Reconciled'`) — per M-014's own comment, these two counts are deliberately at different granularities (lines vs. documents) and are NOT complementary/summable against each other. A future engineer treating all four fields as directly comparable counts (e.g. summing them for a dashboard total) would produce a meaningless number. This route performs zero transformation of M-014's output, so any future change there (e.g. adding a field) flows through automatically with no versioning/compat concern in this route itself.
**Change Impact:** Sole data source for the Home screen's summary stat tiles (M-068). Depends transitively on M-011's `listDocumentsWithStatusBadge()` (via M-014) for document counts and status-badge classification — any change to badge computation logic in M-012 changes `notReconciledCount` here without this route needing modification.
**Callers:** M-068 (HomeView.tsx, fetch)
**Calls:** M-014 (`src/app/api/home-summary/route.ts:6`)
**Integration Points Used:** None (routes through serving-layer modules)
