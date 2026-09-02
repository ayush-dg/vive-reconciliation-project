**Module:** pdfplumberExtractor
**ID:** M-029
**Layer:** pipeline
**Primary Responsibility:** Runs a Python pdfplumber subprocess against a PDF and parses its plaintext output using the SAME synthetic marker format ("INVOICE: X | RO: Y | AMOUNT: Z | DATE: W") as `aiProvider.ts`'s mock — a stand-in for a real per-vendor deterministic layout parser, since no real vendor was onboarded to this path as of this build.

**Inputs:**
- `extractViaPdfplumber(pdfBytes: Buffer)` — writes the bytes to a temp file (`os.tmpdir()/pdfplumber-extract-<pid>-<timestamp>.pdf`) before spawning the subprocess.
- Spawns `scripts/pdfplumber_extract.py <tmpPath>` via `child_process.spawn`, using `process.env.PYTHON_EXECUTABLE ?? 'python'`.

**Outputs:**
- Returns `ExtractionOutcome`. No DB writes. Temp file is always removed in a `finally` block (`fs.rm(tmpPath, { force: true })`), even on failure.

**Public Interface:**
- `export async function extractViaPdfplumber(pdfBytes: Buffer): Promise<ExtractionOutcome>`

**Error Behaviour:**
- Subprocess spawn failure (`child.on('error', reject)`, e.g. `python` executable not found): the returned Promise rejects — propagates uncaught out of `extractViaPdfplumber` to its caller.
- Subprocess produces non-JSON stdout: caught inside the Promise executor and re-thrown as `Error("pdfplumber_extract.py produced non-JSON output: ...")` — still an uncaught rejection from the caller's perspective.
- Subprocess itself reports `{ "error": ... }` (valid JSON, but an error payload): NOT thrown — degrades gracefully to `{ extracted: null, confidence: null, rawOutput: JSON.stringify(result) }`.
- Non-zero subprocess exit code is NOT itself checked (`child.on('close', ...)` doesn't inspect the exit code) — only whether stdout parses as JSON matters; a script that exits non-zero but still prints valid JSON on stdout is silently treated as a normal (possibly error-shaped) result rather than a failure.

**Known Fragility:**
- This module is invoked by TWO distinct call sites in `vendorIdentification.ts` (M-021) for two different purposes: (1) `peekVendorSlug` uses it purely as a cheap text-scan to guess a routing slug BEFORE the real extraction decision is made, and (2) the actual "deterministic" extraction path (`matched.extractionRoute === 'deterministic'`) calls it as the REAL extraction. A future engineer changing this module's behavior to optimize the peek use-case (e.g., limiting pages scanned) would silently degrade real extraction quality for any vendor routed through the deterministic path, and vice versa.
- The marker-format parser (`LINE_PATTERN`) only matches this project's own synthetic test-fixture format — this module cannot extract ANY real-world vendor statement layout. It is explicitly flagged as a stand-in, not production-ready, in its own doc comment. A future engineer who forgets this and routes a real vendor to `extraction_route = 'deterministic'` without first building that vendor's real parser (i.e., without one of the M-032–M-040 wrappers) would get silent, total extraction failure (zero lines matched, no error).
- Temp file naming (`pdfplumber-extract-${process.pid}-${Date.now()}`) is not cryptographically unique — two calls in the same process within the same millisecond (unlikely but not impossible under concurrent processing) could collide.

**Change Impact:** `vendorIdentification.ts` (M-021) is the sole caller. `scripts/pdfplumber_extract.py`'s stdout JSON shape (`{ text: string } | { error: string }`) is a cross-language contract with no compile-time enforcement — a Python-side change to the output shape breaks this TS parser silently at runtime only.

**Callers:** M-021
**Calls:** none listed in the internal call table (spawns `scripts/pdfplumber_extract.py` as an external subprocess)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
