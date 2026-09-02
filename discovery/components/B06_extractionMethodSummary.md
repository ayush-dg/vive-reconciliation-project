**Module:** extractionMethodSummary.ts
**ID:** M-016
**Layer:** serving
**Primary Responsibility:** Per-document count of extraction attempts grouped by `provider_used`, for the Document Detail screen's extraction-method summary panel.

**Inputs:** `getExtractionMethodSummary(documentId: string)` — string id; existence is checked and enforced (see Error Behaviour).

**Outputs:** Read-only, no writes. Returns `ExtractionMethodSummary` (`Record<string, number>`).

**Public Interface:**
- `export type ExtractionMethodSummary = Record<string, number>`
- `export function getExtractionMethodSummary(documentId: string): ExtractionMethodSummary`

**Error Behaviour:** Throws an uncaught `Error` if no `extracted_document` row matches `documentId` — same fail-loud pattern as M-012, deliberately avoiding conflating "zero attempts" with "nonexistent document." `assertSqliteMode()` also throws uncaught if not in SQLite mode. No other try/catch; a DB error propagates uncaught. Caller M-013 does not catch this either — it propagates further up to the API route.

**Known Fragility:**
- `provider_used` NULL rows (a catastrophic pre-provider-selection failure) are `COALESCE`d into an explicit `'unknown'` bucket rather than filtered out — a future new failure mode that also leaves `provider_used` NULL would be silently lumped into the same `'unknown'` bucket with no way to distinguish causes from this summary alone.
- This module and M-012 (`documentStatus.ts`) each independently re-implement the identical "does this document exist" check against `extracted_document` — duplicated, not shared logic; if the fail-loud behavior is changed in one, it's easy to forget the other.

**Change Impact:** M-013 is the sole caller; a change here changes what the Document Detail screen's method-summary panel shows, or (if the throw behavior changes) whether `getDocumentDetail`'s overall call succeeds or throws.

**Callers:** M-013
**Calls:** M-003
**Integration Points Used:** None (routes through M-003)
