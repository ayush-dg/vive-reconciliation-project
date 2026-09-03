**Module:** pdfplumberOcrFallback
**ID:** M-030
**Layer:** pipeline
**Primary Responsibility:** The Task 8.3 last-resort OCR/pdfplumber fallback tier — invoked only after a genuine Claude extraction failure on attempt 1, never tried first and never a substitute for the known-vendor deterministic path.

**Inputs:**
- `extractViaPdfplumberOcrFallback(pdfBytes: Buffer)` — writes bytes to a temp file, spawns `scripts/pdfplumber_ocr_fallback.py <tmpPath>`.

**Outputs:**
- Returns `ExtractionOutcome`. No DB writes. Temp file always removed in `finally`.

**Public Interface:**
- `export async function extractViaPdfplumberOcrFallback(pdfBytes: Buffer): Promise<ExtractionOutcome>`

**Error Behaviour:**
- Same subprocess I/O contract and error handling shape as `pdfplumberExtractor.ts` (M-029): spawn error rejects uncaught; non-JSON stdout rejects with a wrapped error; a `{ error: ... }` JSON payload degrades to `{ extracted: null, confidence: null }` rather than throwing.
- Explicit additional guard not present in M-029: if the subprocess succeeds AND parses but returns ZERO lines (`lines.length === 0`), this is treated as a real failure — `{ extracted: null, confidence: null }` is returned even though the subprocess itself reported success. The module's own comment frames this as deliberate: "No lines at all is a real, honest failure for this last-resort path — never silently promote an empty extraction as if it succeeded."

**Known Fragility:**
- `lineConfidence` is computed ONCE per batch (`result.ocr_pages_used.length > 0 ? 0.5 : 0.65`) and applied UNIFORMLY to every line in the response — the Python side doesn't track which specific page (real table vs. OCR-derived) produced which line, only whether OCR was used anywhere in the document. A statement that's mostly real-table data with just one OCR page would have ALL its lines (including the high-confidence table-derived ones) reported at the lower 0.5 confidence — a future engineer building a per-line confidence UI or threshold off this field would be misled about which specific lines are actually OCR-derived.
- Being the LAST-resort tier (never a substitute for the deterministic path, never tried before Claude), a future engineer routing a document here directly (bypassing `vendorIdentification.ts`'s `forceFallback` gating) would bypass the retry-history assumption baked into `extractionPipeline.ts`'s `routeNextAttemptToFallback` logic — this module has no awareness of, or guard against, being called out of its intended sequence.
- Confidence values (0.5/0.65) are hardcoded constants with no documented derivation beyond "OCR column boundaries are inferred from flat text rather than real table geometry" — a future engineer tuning validation thresholds against these numbers has no empirical basis cited for the specific values chosen.

**Change Impact:** `vendorIdentification.ts` (M-021) is the sole caller, invoked only when `forceFallback === true`. `scripts/pdfplumber_ocr_fallback.py`'s JSON output shape (`vendor_name_guess`, `statement_period`, `statement_total`, `lines[]`, `warnings[]`, `ocr_pages_used[]`, `ocr_available`) is a cross-language contract enforced only at runtime.

**Callers:** M-021
**Calls:** none listed in the internal call table (spawns `scripts/pdfplumber_ocr_fallback.py` as an external subprocess)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
