**Module:** documentDetail.ts
**ID:** M-013
**Layer:** serving
**Primary Responsibility:** Assembles the full Document Detail screen dataset for one document — header/status info, extraction-method summary, per-line statement rows with confidence/provider, and line-level reconciliation counts.

**Inputs:** `getDocumentDetail(documentId: string)` — string id. No explicit validation beyond `getDocumentById` (M-011) returning `null` for a nonexistent document.

**Outputs:** Read-only, no writes. Returns `DocumentDetailData | null` (`null` when the document doesn't exist).

**Public Interface:**
- `export type StatementLineRow = { lineId, invoiceRef, amount, confidence, providerUsed }`
- `export type ReconciliationCounts = { totalLines, matchedLines, exceptionLines }`
- `export type DocumentDetailData = { documentId, vendorSlug, statementPeriod, status, statusBadge, extractionMethodSummary, lines, reconciliation }`
- `export function getDocumentDetail(documentId: string): DocumentDetailData | null`
(`getStatementLinesForDocument` and `getReconciliationCounts` are internal, not exported.)

**Error Behaviour:** `getDocumentDetail` has no try/catch of its own. If `getDocumentById` (M-011) returns `null`, the function short-circuits and returns `null` cleanly — a real "not found" signal, not an exception. However `computeDocumentStatus` (M-012) and `getExtractionMethodSummary` (M-016) each re-run their own independent existence check against `extracted_document`; if the document were somehow deleted between the initial `getDocumentById` call and those later calls (a narrow, untraced race), either would throw uncaught, and this module provides no catch to soften that — the exception propagates straight to the caller (M-045).

**Known Fragility:**
- Per-line `confidence`/`providerUsed` are derived via a correlated subquery picking the single successful attempt (`ORDER BY attempt_no DESC LIMIT 1`), documented as safe only because `extractionPipeline.ts`'s idempotency guard (elsewhere) ensures at most one successful attempt per document. That invariant is not enforced by this module itself — if it's ever violated, the subquery silently picks the latest successful attempt rather than erroring, potentially misattributing confidence/provider.
- Three logically-independent existence checks are performed across three different modules for one `getDocumentDetail` call (`getDocumentById` here, `computeDocumentStatus` in M-012, `getExtractionMethodSummary` in M-016) instead of one shared guard — a maintenance seam if any one module's existence semantics ever diverges from the others.
- `ReconciliationCounts`' documented invariant (`matchedLines + exceptionLines` should be `0` or `totalLines`, never partial) is not runtime-asserted anywhere in this module — a bug elsewhere (e.g. a crash mid-matching-commit) could silently surface a partial count here with no error raised.

**Change Impact:** M-045 is the sole direct API-route caller, and M-075 (the Document Detail page) also calls this module directly for SSR — the Document Detail screen (M-075/M-076) depends on this entirely. Because this module calls M-011, M-012, and M-016, a breaking change in any of those three cascades here and then to the Document Detail screen's rendered output.

**Callers:** M-045, M-075
**Calls:** M-003, M-011, M-012, M-016
**Integration Points Used:** None (routes through M-003)
