**Module:** extractPrecision
**ID:** M-038
**Layer:** pipeline
**Primary Responsibility:** Known-vendor deterministic extractor for Precision Diagnostics, Inc. — spawns `scripts/extract_precision.py` as a subprocess and converts its JSON output into this project's `ExtractionOutcome`/`ExtractedStatement` shape.

**Inputs:** `extractViaPrecision(pdfBytes: Buffer)`. Spawns `python scripts/extract_precision.py <tmpPath>`.

**Outputs:** Returns `ExtractionOutcome`. No DB writes; no other side effects.

**Public Interface:** `export async function extractViaPrecision(pdfBytes: Buffer): Promise<ExtractionOutcome>`; `export const PRECISION_SIGNATURES = ['Precision Diagnostics']`; `export const PRECISION_VENDOR_SLUG = 'precision_diagnostics'`.

**Reconciliation rule (Python side, `scripts/extract_precision.py`):** The distinctive mechanic here is MULTI-LINE transaction reconstruction — a single logical transaction's vehicle description/VIN/RO fragments are spread across several physical PDF rows. The parser accumulates `description_tokens`/`charge_tokens` across continuation rows (any row whose leading x0 is ≥150 and doesn't itself start a new dated transaction) until the next row with a valid `^\d{1,2}/\d{1,2}/\d{4}$` date starts a new transaction, at which point the PREVIOUS accumulated transaction is finalized. Sums the **`charge`** column (x0 100–450 bucketed into `charge`/`payment` sub-ranges, but only `charge` is actually used as this project's `amount`). Invoice number is extracted from the reconstructed description via `#INV(\d+)`. Rows whose finalized description is exactly "balance forward" (case-insensitive) are explicitly excluded from `line_items`. Total is the page-1 `"Amount Due"` figure, falling back to the computed sum. Documented as NOT a correctness fix — Claude already extracts this vendor's amounts correctly via the generic path (27/27 matched in the reference project's own eval); this port is for cost/reliability only.

**Error Behaviour:** Same subprocess error contract as the other wrappers.

**Known Fragility:** The multi-line accumulation state machine (`current_txn`, finalized only when a new dated row appears or the page ends) is the most STATEFUL parsing logic among all 9 wrappers — a transaction whose continuation rows are interrupted by an unrelated row that happens to also have `leading_x0 < 150` would cause the loop to `break` out of the page entirely (`elif leading_x0 < 150: break`), silently truncating extraction of the REST of that page's transactions with no error or warning.

**Change Impact:** Registered in `knownVendorExtractors.ts` (M-031). Since Claude already handles this vendor correctly, a regression here degrades reliability/cost but is less likely to be caught by a simple "does the total match" smoke test if the generic path would have quietly produced the right answer anyway in a fallback scenario — though this deterministic path, once matched, is what actually runs; there is no automatic fallback to Claude for a known vendor.

**Callers:** M-021 (via M-031's registry, dynamic dispatch — one of 9)
**Calls:** none (spawns `scripts/extract_precision.py` as an external subprocess)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
