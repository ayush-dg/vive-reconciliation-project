**Module:** extractKeystone
**ID:** M-036
**Layer:** pipeline
**Primary Responsibility:** Known-vendor deterministic extractor for Keystone Automotive Industries — spawns `scripts/extract_keystone.py` as a subprocess and converts its JSON output into this project's `ExtractionOutcome`/`ExtractedStatement` shape.

**Inputs:** `extractViaKeystone(pdfBytes: Buffer)`. Spawns `python scripts/extract_keystone.py <tmpPath>`.

**Outputs:** Returns `ExtractionOutcome`. No DB writes; no other side effects.

**Public Interface:** `export async function extractViaKeystone(pdfBytes: Buffer): Promise<ExtractionOutcome>`; `export const KEYSTONE_SIGNATURES = ['Keystone Automotive Industries']`; `export const KEYSTONE_VENDOR_SLUG = 'keystone_automotive_industries'`.

**Reconciliation rule (Python side, `scripts/extract_keystone.py`):** Word-position column bucketing across EIGHT columns by fixed x0 ranges (`reference_date`, `reference_number`, `purchase_order_number`, `balance_forward`, `period_activity`, `credit_applied`, `payment_applied`, `balance_due`). The extractor sums **"Balance Due"** — this column already NETS `Balance Forward + Period Activity − Credit Applied − Payment Applied` per row; none of the other 7 columns are used as the amount. A row counts as a line item only if `reference_date` matches `^\d{2}/\d{2}/\d{2}$`. Total is the page-1 `"AMOUNT DUE:"` figure, falling back to the computed sum. **Claude's generic vision path scored 0% on this vendor** (every line's sign/value came back wrong) — the module's own docstring states no generic prompt can be expected to reverse-engineer the netting rule from a page scan, and the fix was cross-verified against both the printed "Month Totals" row and the page-1 "AMOUNT DUE" figure.

**Error Behaviour:** Same subprocess error contract as the other wrappers.

**Known Fragility:** Eight tightly-packed column boundaries with sub-pixel-precision thresholds (e.g. `84.45`, `152.3`, `244.2`, `323.0`, `387.4`, `451.95`, `523.25`) measured from one specific document's header word positions — this is the most granular column layout among all 9 vendors and correspondingly the most sensitive to any template change; a shifted column by even a few pixels could misroute a value from `payment_applied` into `balance_due` (or vice versa), silently changing every line's sign/magnitude given the netting relationship, with the 0%-baseline Claude fallback meaning there's no adjacent "at least partially right" degraded mode if this breaks.

**Change Impact:** Registered in `knownVendorExtractors.ts` (M-031). Given the 0% generic-fallback baseline, this vendor has NO safety net if this deterministic path regresses — a bug here is not masked by "at least the AI got it roughly right."

**Callers:** M-021 (via M-031's registry, dynamic dispatch — one of 9)
**Calls:** none (spawns `scripts/extract_keystone.py` as an external subprocess)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
