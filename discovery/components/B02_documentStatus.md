**Module:** documentStatus.ts
**ID:** M-012
**Layer:** serving
**Primary Responsibility:** Computes the single source-of-truth display status badge for a document (Processing / Extracted / Reconciling / Retrying / Failed / Reconciled) from lock, match, exception, and extraction-attempt state, in a fixed precedence order.

**Inputs:** `computeDocumentStatus(documentId: string)` — string document id, no other parameters. Existence is checked explicitly and enforced (see Error Behaviour).

**Outputs:** Read-only — no DB writes anywhere in this module. Returns `DocumentStatusResult { badge, label, attemptCount }`.

**Public Interface:**
- `export type DocumentStatusBadge = 'Processing' | 'Extracted' | 'Reconciling' | 'Retrying' | 'Failed' | 'Reconciled'`
- `export type DocumentStatusResult = { badge: DocumentStatusBadge; label: string; attemptCount: number }`
- `export function computeDocumentStatus(documentId: string): DocumentStatusResult`

**Error Behaviour:** Throws an uncaught `Error` if `documentId` does not exist in `extracted_document` — deliberate fail-loud so a stale/mistyped/deleted id can't be misread as a legitimate zero-attempt new document (both would otherwise have zero attempt rows). `assertSqliteMode()` also throws uncaught if not in SQLite mode. No try/catch anywhere in this module — callers (M-011, M-013, M-044) experience the raw exception directly with no fallback badge produced.

**Known Fragility:** [NOTABLE — S7 status-badge finding, precisely characterized] The branch order (lock check → full-reconciled check → open-exception check → latest-attempt logic) is load-bearing; reordering silently changes precedence in ambiguous states. On the "attempt 1 failed, attempt 2 succeeded" bounded-retry path, this function correctly evaluates `latestSucceeded = true` and returns `badge: 'Extracted'` (matching-eligible, awaiting Reconcile) — this is the module's actual, current, semantically-correct behavior per its own documented five-value badge design (2026-08-31 addition split the old single "Processing" value into "Processing" vs "Extracted"). The project's recorded **"S7 FAIL"** in `verification/VERIFICATION_CHECKLIST.md` traces to `scripts/test_bounded_retry.mjs:58`'s assertion `check('TC-1: ... (Processing badge, not Failed/Retrying)', status.badge === 'Processing')` — that literal-string assertion was written against the older four-badge vocabulary and was never updated after the `'Extracted'` badge was introduced. The test fails because the badge is (correctly) `'Extracted'`, not because the badge-computation logic is wrong. This is stale-test/spec-drift, not a live production defect in this module's logic as read — but it is recorded project-wide as an open FAIL, and a future engineer should re-verify on these exact terms (fix the test's expected value, or confirm intent) rather than assume the status computation itself needs repair.
- `LOCK_STALE_AFTER_MINUTES` is imported directly as a value from M-017 (`matchingInvocation.ts`), not duplicated — a future change to that constant in M-017 silently changes this module's "Reconciling" staleness window too; easy to miss since it's a plain value import, not a function call.
- "Reconciled" requires `totalLines > 0 AND matchedLines === totalLines` — a document with zero statement lines can never show "Reconciled," falling through toward Processing/Extracted/Failed instead; presumably intended but a subtle edge to get wrong.

**Change Impact:** M-011 (`listDocumentsWithStatusBadge`), M-013 (`getDocumentDetail`), and M-044 all call this directly — the Document List/Upload/Home screens and the Document Detail screen all display whatever this function returns. Any change to badge/label semantics changes what every one of those screens shows.

**Callers:** M-011, M-013, M-044
**Calls:** M-003
**Integration Points Used:** None (routes through M-003)

**Data-reference (non-call) dependency:** Reads `LOCK_STALE_AFTER_MINUTES` constant from M-017 — a value read, not a function call.
