**Module:** homeSummary.ts
**ID:** M-014
**Layer:** serving
**Primary Responsibility:** Computes Home screen summary statistics (documents processed, open exceptions, reconciled/not-reconciled counts) by aggregating `listDocumentsWithStatusBadge` output plus direct exception/match table counts.

**Inputs:** `getHomeSummaryStats()` — no parameters.

**Outputs:** Read-only, no writes. Returns `HomeSummaryStats { documentsProcessed, openExceptions, reconciledCount, notReconciledCount }`.

**Public Interface:**
- `export type HomeSummaryStats`
- `export function getHomeSummaryStats(): HomeSummaryStats`

**Error Behaviour:** No try/catch in this module. `assertSqliteMode()` throws uncaught if not in SQLite mode. `listDocumentsWithStatusBadge()` (M-011, which itself calls `computeDocumentStatus`/M-012 per document) can throw uncaught if any underlying document is inconsistent (e.g. `computeDocumentStatus`'s own "no document found" fail-loud check) — propagates directly to the caller (M-052) with no fallback stats produced.

**Known Fragility:**
- `notReconciledCount` is `documents.length - fullyReconciledDocs`, i.e. "documents not yet fully reconciled" — this includes documents that haven't even started matching (status Processing/Extracted), not just ones with genuine exceptions. A future consumer could misread it as "documents with exceptions." Also note the four returned fields mix units: `reconciledCount` is line-level (from `recon_match`), while `notReconciledCount` and `documentsProcessed` are document-level — they are not simple complements of the same universe, an easy mistake for a future API consumer.
- Calls `listDocumentsWithStatusBadge()`, which computes `computeDocumentStatus` per document unbatched — the same N+1-style latent scaling fragility noted for M-011, incurred on every Home-summary fetch.

**Change Impact:** M-052 is the sole caller; the Home screen's stat tiles (rendered via M-068 `HomeView.tsx`, which fetches M-052) depend entirely on this module's four fields. A change to `HomeSummaryStats`' field semantics or names breaks the Home screen display directly.

**Callers:** M-052
**Calls:** M-003, M-011
**Integration Points Used:** None (routes through M-003)
