**Module:** extractQuirk
**ID:** M-039
**Layer:** pipeline
**Primary Responsibility:** Known-vendor deterministic extractor for Quirk Auto Group — spawns `scripts/extract_quirk.py` as a subprocess and converts its JSON output into this project's `ExtractionOutcome`/`ExtractedStatement` shape.

**Inputs:** `extractViaQuirk(pdfBytes: Buffer)`. Spawns `python scripts/extract_quirk.py <tmpPath>`.

**Outputs:** Returns `ExtractionOutcome`. No DB writes; no other side effects.

**Public Interface:** `export async function extractViaQuirk(pdfBytes: Buffer): Promise<ExtractionOutcome>`; `export const QUIRK_SIGNATURES = ['QUIRK AUTO GROUP']`; `export const QUIRK_VENDOR_SLUG = 'quirk_auto_group'`.

**Reconciliation rule (Python side, `scripts/extract_quirk.py`):** Distinctive mechanics: (1) drops words with `x0 < 28` before any parsing — a watermark-filtering step (`WATERMARK_MAX_X1`) unique to this vendor among the 9. (2) Classifies money tokens by right-edge into `amount` (x1 ≤ 400) vs. `remit_balance` (beyond) and uses only `amount`. (3) A row counts as a line item only if it has BOTH a date matching `^\d{2}-\d{2}$` (no year — borrowed later from the statement date) AND a non-empty `invoice` field. Sums the **`amount`** column — already a single signed value (positive=charge, negative=credit/memo) as printed, no separate sign-flip step needed (unlike Fred Beans' split charges/credits). Total is found by locating a "NEW"/"BALANCE" label row on the LAST page and taking the nearest money token (within 40px x0) from up to 2 rows below it, falling back to the computed sum. The generic Claude fallback scored 82.8% on this vendor.

**Error Behaviour:** Same subprocess error contract as the other wrappers.

**Known Fragility:** The watermark-drop threshold (`x0 < 28`) is a fixed pixel cutoff with no validation that it's actually filtering a watermark rather than legitimate leftmost content — a future Quirk statement with genuine data starting at x0 < 28 (e.g. a narrower-margin reprint) would have that data silently discarded before parsing even begins, with no diagnostic trail distinguishing "watermark correctly filtered" from "real data incorrectly dropped." The date has no year of its own (`MM-DD` only) and borrows the statement's year via `normalize_date` — a statement spanning a year boundary (e.g. December transactions on a January-dated statement) would get the WRONG year silently applied to every borrowed date.

**Change Impact:** Registered in `knownVendorExtractors.ts` (M-031).

**Callers:** M-021 (via M-031's registry, dynamic dispatch — one of 9)
**Calls:** none (spawns `scripts/extract_quirk.py` as an external subprocess)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
