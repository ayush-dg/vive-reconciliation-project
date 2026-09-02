**Module:** extractWilberts
**ID:** M-040
**Layer:** pipeline
**Primary Responsibility:** Known-vendor deterministic extractor for Wilbert's Inc. — spawns `scripts/extract_wilberts.py` as a subprocess and converts its JSON output into this project's `ExtractionOutcome`/`ExtractedStatement` shape.

**Inputs:** `extractViaWilberts(pdfBytes: Buffer)`. Spawns `python scripts/extract_wilberts.py <tmpPath>`.

**Outputs:** Returns `ExtractionOutcome`. No DB writes; no other side effects.

**Public Interface:** `export async function extractViaWilberts(pdfBytes: Buffer): Promise<ExtractionOutcome>`; `export const WILBERTS_SIGNATURES = ["Wilbert's Inc"]`; `export const WILBERTS_VENDOR_SLUG = 'wilberts_inc'`.

**Reconciliation rule (Python side, `scripts/extract_wilberts.py`):** Sums the **"Balance"** column (x0 395–460), explicitly NOT the "Amount" column — the module's own doc comment states this is deliberate: Amount and Balance disagree on the sole lump-sum Payment row, and summing Amount instead double-counts. A row is only recognized as a line item if it has a valid date (`^\d{2}/\d{2}/\d{2}$`) AND a money-shaped token present in a separate x0 range (285–335, the unused "amount" zone) purely as a PRESENCE check (`amount_present`), NOT as the value actually extracted — that same-range Amount value is deliberately never read into `line_items`. Money format uses parenthesized-negative convention (`($320.20)` → `-320.20`), parsed by `clean_money`. Continuation rows matching `^DT#\d+$` in the `reference` column get appended onto the PREVIOUS line item's `reference` field (multi-row reference reconstruction), not treated as new line items. Columns beyond x0=460 are an intentionally-ignored duplicate remittance-stub. Total is `"Balance Due"` printed on the last page. The generic Claude fallback scored only 64% on this vendor, missing every credit-memo row specifically because of the Amount/Balance disagreement on the lump-sum Payment row.

**Error Behaviour:** Same subprocess error contract as the other wrappers.

**Known Fragility:** This is the module the task brief explicitly calls out — confirmed: Wilbert's sums "Balance," not "Amount." The `amount_present` presence-only check (reading from x0 285–335 purely to decide "is this a real line row," while the actual VALUE used comes from the separate 395–460 `balance` bucket) is a subtle two-column dependency — a future engineer "simplifying" this by reading the value directly from the `amount_present` check's own column (since it's already being scanned) would silently reintroduce exactly the Amount-vs-Balance bug this port exists to fix. The `DT#` continuation-row merge assumes continuation rows always immediately follow their parent line item in `line_items` (`line_items[-1]`) — a continuation row appearing before any line item has been added (e.g. a malformed first page) is silently dropped (`and line_items` guards against a crash but not against data loss).

**Change Impact:** Registered in `knownVendorExtractors.ts` (M-031). Given the 64% Claude-fallback baseline and the specific credit-memo miss pattern, a regression here is a correctness risk with a known historical precedent, not just a reliability one.

**Callers:** M-021 (via M-031's registry, dynamic dispatch — one of 9)
**Calls:** none (spawns `scripts/extract_wilberts.py` as an external subprocess)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
