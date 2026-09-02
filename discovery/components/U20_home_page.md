**Module:** Home Page
**ID:** M-067
**Layer:** page
**Primary Responsibility:** Server-fetches the initial document list and summary stats, then hands them to `HomeView` as the Dashboard screen's initial data.

**Inputs (Props):** None (no route params/searchParams).
**Outputs (Rendered UI + Side Effects):** Calls `listDocumentsWithStatusBadge()` (M-011) and `getHomeSummaryStats()` (M-014) synchronously at render time (both are synchronous lib calls, not awaited — server component but not `async`), then renders `<HomeView initialDocuments={documents} stats={stats} />` (M-068). No other side effects.
**State Consumed:** None.
**Public Interface:** `export default function HomePage()`.
**Error Behaviour:** No try/catch — if either lib call throws, the error propagates to `(app)/error.tsx` (M-066).
**Known Fragility:** Not `async` despite fetching data — relies on M-011/M-014 being synchronous (in-memory or otherwise non-Promise) implementations; if either is later changed to an async/DB call, this module would need to become `async` and `await` them, or it would pass a Promise instead of data into `HomeView`, silently breaking rendering.
**Change Impact:** Changes to `ApiDocument` shape (M-011) or `HomeSummaryStats` shape (M-014) directly affect what `HomeView` (M-068) can render — both are passed through as typed props with no transformation in this module.
**Callers:** Framework-invoked for route `/home`; not imported elsewhere.
**Calls:** M-011 (`documents.ts` `listDocumentsWithStatusBadge`, page.tsx:9), M-014 (`homeSummary.ts` `getHomeSummaryStats`, page.tsx:10).
**Renders:** M-068 (HomeView).
**Integration Points Used:** None (fetches internal API routes only) — N/A, calls lib functions directly server-side, not a fetch.
