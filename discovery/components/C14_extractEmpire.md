**Module:** extractEmpire
**ID:** M-034
**Layer:** pipeline
**Primary Responsibility:** Known-vendor deterministic extractor for Empire Auto Parts — spawns `scripts/extract_empire.py` as a subprocess and converts its JSON output into this project's `ExtractionOutcome`/`ExtractedStatement` shape.

**Inputs:** `extractViaEmpire(pdfBytes: Buffer)`. Spawns `python scripts/extract_empire.py <tmpPath>`.

**Outputs:** Returns `ExtractionOutcome`. No DB writes; no other side effects.

**Public Interface:** `export async function extractViaEmpire(pdfBytes: Buffer): Promise<ExtractionOutcome>`; `export const EMPIRE_SIGNATURES = ['EMPIRE AUTO PARTS']`; `export const EMPIRE_VENDOR_SLUG = 'empire_auto_parts'`.

**Reconciliation rule (Python side, `scripts/extract_empire.py`):** Word-position column bucketing by fixed `x0` ranges (`transaction_date` 0–65, `description` 65–200, `doc_no` 200–260, `amount` 420–470). Sums the single **`amount`** column (signed value directly, positive/negative as printed — no separate charge/credit split for this vendor). The distinctive fixup: this layout merges the description and 7–9 digit doc-number into one adjacent token (e.g. "Highlander40444218"); if the `doc_no` column bucket is empty, the code regexes a trailing `\d{7,9}` off the LAST description word to recover it. A row only counts as a real line item if BOTH the date matches `^\d{2}/\d{2}/\d{2}$` AND the recovered `doc_no` matches `^\d{7,9}$`. Total is `"Total Balance:"` printed on the page, falling back to the computed sum. The generic Claude fallback scored 81.3% on this vendor, consistently mis-splitting the merged description/doc-number token — this is the exact case this port's un-merge fixup exists to solve.

**Error Behaviour:** Same subprocess error contract as the other wrappers.

**Known Fragility:** The doc-number recovery fallback (regex off the last description word) is a heuristic specific to THIS vendor's exact merge pattern — a future Empire statement where the doc-number merges onto a DIFFERENT word position, or where a description word coincidentally ends in 7–9 digits for an unrelated reason, would silently produce a wrong or spurious `doc_no`. Column x0-boundaries (`COLUMN_BOUNDS`) are hardcoded pixel measurements from one specific document layout — any Empire template change shifting column positions breaks bucketing silently (rows simply fail the `DATE_RE`/`DOC_NO_RE` gate and are dropped, not flagged).

**Change Impact:** Registered in `knownVendorExtractors.ts` (M-031). A layout change from this vendor requires re-measuring `COLUMN_BOUNDS` — no auto-detection exists.

**Callers:** M-021 (via M-031's registry, dynamic dispatch — one of 9)
**Calls:** none (spawns `scripts/extract_empire.py` as an external subprocess)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
