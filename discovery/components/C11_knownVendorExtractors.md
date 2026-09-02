**Module:** knownVendorExtractors
**ID:** M-031
**Layer:** pipeline
**Primary Responsibility:** Table-driven registry of the 9 known-vendor deterministic extractors (M-032–M-040); matches a document's raw text against each vendor's real printed signature strings and returns the first match, replacing Task 8.1's single hardcoded Lia-only special case.

**Inputs:**
- `findKnownVendorExtractor(pdfText: string)` — the document's raw extracted text (from the real, non-synthetic PDF, as opposed to the "VENDOR: <name>" test-fixture marker other paths use).
- Statically imports `extract*`/`*_SIGNATURES`/`*_VENDOR_SLUG` from all 9 vendor wrapper modules at module load time.

**Outputs:**
- Returns `KnownVendorExtractor | null` — a plain read, no side effects, no DB access, no I/O of its own (all I/O lives inside whichever wrapper's `.extract()` eventually gets called by the caller).

**Public Interface:**
- `export function findKnownVendorExtractor(pdfText: string): KnownVendorExtractor | null`
- `export const KNOWN_VENDOR_EXTRACTORS: KnownVendorExtractor[]` — array of `{ vendorSlug, signatures, extract }`.
- `export type KnownVendorExtractor = { vendorSlug: string; signatures: string[]; extract: (pdfBytes: Buffer) => Promise<ExtractionOutcome> }`

**Error Behaviour:** Never throws — `Array.prototype.find` with `.some()` over `signatures.some((sig) => pdfText.includes(sig))` either finds a match or falls through to `null`. Purely synchronous; the returned `extract` function is not invoked here, so any error it would raise is entirely the caller's concern.

**Known Fragility:**
- Signature matching is a simple `pdfText.includes(sig)` substring check with NO scoping/ordering guarantee against a genuinely ambiguous document containing multiple vendors' signature strings (e.g. a scanned cover letter that happens to mention "Keystone Automotive Industries" while being a genuinely different vendor's statement) — `Array.find` returns the FIRST matching entry in array-declaration order, so array order is a silent priority ranking. Adding a new vendor whose signature substring happens to also appear inside a different, already-registered vendor's typical document text would silently mis-route documents depending only on declaration order.
- Each vendor's `signatures` array is manually kept in sync with the corresponding Python script's own `VENDOR_SIGNATURE` list (confirmed for Lia: "there's no shared source between a Python list and this TS array," per `extractLiaAutoGroup.ts`'s own doc comment) — a future engineer updating one without the other would create a split-brain state where the TS routing layer and the Python script's own self-description disagree, though the Python script's own `VENDOR_SIGNATURE` isn't actually consulted for routing (only this TS array is) — so a Python-side edit alone has NO effect on real routing at all, which is easy to miss.
- Registering a new vendor here is explicitly wiring, not an invocation (per the task's own framing) — it happens at module load time via static imports, meaning EVERY known-vendor wrapper module is loaded into memory whenever `vendorIdentification.ts` is loaded, regardless of whether that vendor is ever actually seen; a wrapper module with a top-level side effect or expensive import would affect every extraction pipeline load, not just its own vendor's documents.

**Change Impact:** `vendorIdentification.ts` (M-021) is the sole caller of `findKnownVendorExtractor`. Adding a 10th vendor means adding one array entry here plus a new wrapper module — no change needed in `vendorIdentification.ts`'s routing logic itself (this was the explicit point of Session 9's refactor away from Task 8.1's single hardcoded branch). Removing or renaming any of the 9 wrapper modules' exports breaks this file's static imports at compile time.

**Callers:** M-021
**Calls:** none (wires/registers M-032–M-040 at load time — not a Calls/invocation edge, per the reference data)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
