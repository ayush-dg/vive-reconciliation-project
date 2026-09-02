**Module:** extractAdas
**ID:** M-032
**Layer:** pipeline
**Primary Responsibility:** Known-vendor deterministic extractor for Adas Calibration Experts — spawns `scripts/extract_adas.py` as a subprocess and converts its JSON output into this project's `ExtractionOutcome`/`ExtractedStatement` shape.

**Inputs:** `extractViaAdas(pdfBytes: Buffer)`. Spawns `python scripts/extract_adas.py <tmpPath>` (temp file written from `pdfBytes`, always removed in `finally`).

**Outputs:** Returns `ExtractionOutcome`. No DB writes; no other side effects.

**Public Interface:** `export async function extractViaAdas(pdfBytes: Buffer): Promise<ExtractionOutcome>`; `export const ADAS_SIGNATURES = ['Adas Calibration Experts']`; `export const ADAS_VENDOR_SLUG = 'adas_calibration_experts'`.

**Reconciliation rule (Python side, `scripts/extract_adas.py`):** Each line matches a fixed regex `"<date> Invoice #<n>: Due <date>. <amount> <open_amount>"`. The extractor sums **OPEN AMOUNT**, not AMOUNT — the module's own doc comment explains this deliberately: AMOUNT is the original invoice amount, OPEN AMOUNT is what's still unpaid; an older, already-paid invoice shows a real non-zero AMOUNT but a correct $0.00 OPEN AMOUNT. Reading AMOUNT instead silently overstates every closed invoice (flagged as the exact trap the generic Claude fallback fell into, scoring 87.5% with this AMOUNT-vs-OPEN-AMOUNT confusion on every mismatch). `line_confidence` is hardcoded to `1.0` for every line (real geometry/regex-based parsing, not a guess).

**Error Behaviour:** Spawn error / non-JSON stdout: uncaught rejection to caller. Subprocess `{ "error": ... }` payload: degrades to `{ extracted: null, confidence: null }`.

**Known Fragility:** The `LINE_RE` regex is rigid (exact literal text "Invoice #" and "Due", exact date format) — any layout drift in a future Adas statement (different date format, reworded label) would silently produce ZERO matched lines rather than an error, since a non-matching line is just skipped, not flagged.

**Change Impact:** Registered in `knownVendorExtractors.ts` (M-031). Breaking the JSON output shape of `extract_adas.py` breaks this wrapper silently at runtime only (no compile-time cross-language check).

**Callers:** M-021 (via M-031's registry, dynamic dispatch — one of 9)
**Calls:** none (spawns `scripts/extract_adas.py` as an external subprocess)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
