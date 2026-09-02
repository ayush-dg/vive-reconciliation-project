**Module:** extractAstech
**ID:** M-033
**Layer:** pipeline
**Primary Responsibility:** Known-vendor deterministic extractor for asTech (Repairify) — spawns `scripts/extract_astech.py` as a subprocess and converts its JSON output into this project's `ExtractionOutcome`/`ExtractedStatement` shape.

**Inputs:** `extractViaAstech(pdfBytes: Buffer)`. Spawns `python scripts/extract_astech.py <tmpPath>`.

**Outputs:** Returns `ExtractionOutcome`. No DB writes; no other side effects.

**Public Interface:** `export async function extractViaAstech(pdfBytes: Buffer): Promise<ExtractionOutcome>`; `export const ASTECH_SIGNATURES = ['asTech', 'Repairify']`; `export const ASTECH_VENDOR_SLUG = 'astech_repairify'`.

**Reconciliation rule (Python side, `scripts/extract_astech.py`):** Uses pdfplumber's native table detection (no manual word-position bucketing needed — this layout parses cleanly). Sums the **"Outstanding Amount"** column (row index 4 of the extracted table, header `["Invoice Date", "Invoice #", "Work Order #", "RO #", "Outstanding Amount", "Due Date"]`). Skips rows labeled "Total Outstanding" / "Total Unapplied" and any row whose first cell isn't a `MM/DD/YYYY` date. `vendor_name_guess` is hardcoded to `"asTech (Repairify, Inc.)"`. Notably documented as NOT a correctness fix — Claude's generic vision path already extracts this vendor correctly (106/106 lines, confirmed 2026-09-01); this port exists purely for cost/reliability, not because the generic path was wrong.

**Error Behaviour:** Same subprocess error contract as the other wrappers (spawn/non-JSON uncaught; `{error}` payload degrades to `extracted: null`).

**Known Fragility:** Relies entirely on `page.extract_table()` returning a well-formed table with the exact expected `HEADER_ROW` sequence — a future asTech statement rendered with slightly different column headers or as a non-tabular layout would produce zero matched rows silently (no fallback to word-position parsing exists in this wrapper, unlike several of its siblings).

**Change Impact:** Registered in `knownVendorExtractors.ts` (M-031). Since this vendor is also correctly handled by the generic Claude path, a bug introduced here would degrade reliability/cost but likely NOT correctness in the same visible way as vendors where Claude scores poorly (e.g. Keystone, Wilbert's) — making a regression here comparatively easy to miss without dedicated tests.

**Callers:** M-021 (via M-031's registry, dynamic dispatch — one of 9)
**Calls:** none (spawns `scripts/extract_astech.py` as an external subprocess)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
