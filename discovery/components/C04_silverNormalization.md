**Module:** silverNormalization
**ID:** M-024
**Layer:** pipeline
**Primary Responsibility:** Writes one `silver_statement_line` row per extracted line for a document that passed validation, normalizing the invoice reference and flagging (but not blocking) cross-document duplicates.

**Inputs:**
- `documentId: string`, `vendorId: string`, `statement: ExtractedStatement` — all three required params to `normalizeToSilver`. No internal re-validation that the document actually passed the gate — trusts the caller (`extractionPipeline.ts`) to only invoke this after confirming `ValidationResult.status === 'pass'`; the module's own doc comment states it "has no way to distinguish 'eligible, zero lines' from 'not called' otherwise."
- Reads `silver_statement_line` (for the duplicate check, scoped by `vendor_id + normalized_invoice_ref + amount`, across ALL documents for that vendor, not just the current one).
- SQLite-only (`assertSqliteMode()`).

**Outputs:**
- `INSERT INTO silver_statement_line` once per line in `statement.lines`, inside one transaction (`db.transaction`) — all-or-nothing per document.
- Returns `number` — the count of lines written (`statement.lines.length`).

**Public Interface:**
- `export function normalizeToSilver(documentId: string, vendorId: string, statement: ExtractedStatement): number`
- `export const NORMALIZATION_VERSION = 'v1'`

**Error Behaviour:** Does not itself catch anything — a DB write failure (constraint violation, closed connection) inside the transaction propagates as an uncaught exception to the caller. `extractionPipeline.ts` (M-022) wraps this specific call in its own try/catch and re-throws with added context (see M-022's contract) — the only place in the extraction pipeline that deliberately lets an error surface past the attempt-row commit, since the attempt already correctly recorded "passed validation."

**Known Fragility:**
- `amount` column is `NOT NULL` at the schema level — a blank/credit line (`line.amount === null`) is coerced to `0` here (`line.amount ?? 0`), described as "per S11's immutability guarantee applying from this point on, not a business rule about what 0 'means'" — a future engineer reading Silver data alone (without this comment) could mistake a genuinely-blank-amount credit line for an actual $0.00 transaction.
- Duplicate detection (`isDuplicateLine`) is scoped by `vendor_id + normalized_invoice_ref + amount` across the ENTIRE vendor's history, not just the current document — a legitimately repeated invoice number+amount combination from a genuinely different (non-duplicate) transaction would be flagged `is_duplicate_line=1` with no way to distinguish "true duplicate" from "coincidental same amount, same ref, different real invoice."
- Task 8.5's flagged-but-still-written design (a duplicate line still reaches matching/exceptions exactly like any other row) is an explicit, engineer-directed choice — a future engineer "fixing" duplicates by filtering them out before Silver would silently change what matching/exceptions ever see, contradicting migration 009's documented intent.
- No re-check that validation actually passed — calling this function directly (bypassing `extractionPipeline.ts`) for a document that failed validation would silently write Silver rows with no gate at all.

**Change Impact:** `NORMALIZATION_VERSION` is stamped onto every row and, per S6, historical rows are never rewritten when normalization logic changes — bumping this constant is the only sanctioned way to signal a logic change; failing to bump it while changing `normalizeInvoiceRef`'s logic would silently mix old- and new-logic rows under the same version tag. `matchingPipeline.ts` (M-025) reads `silver_statement_line` rows this module produces (via `normalized_invoice_ref`/`amount`) — changing the normalization rule changes what matching sees as the join key.

**Callers:** M-022
**Calls:** M-003 (21,40,66)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
