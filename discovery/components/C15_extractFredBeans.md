**Module:** extractFredBeans
**ID:** M-035
**Layer:** pipeline
**Primary Responsibility:** Known-vendor deterministic extractor for Fred Beans Parts — spawns `scripts/extract_fred_beans.py` as a subprocess and converts its JSON output into this project's `ExtractionOutcome`/`ExtractedStatement` shape.

**Inputs:** `extractViaFredBeans(pdfBytes: Buffer)`. Spawns `python scripts/extract_fred_beans.py <tmpPath>`.

**Outputs:** Returns `ExtractionOutcome`. No DB writes; no other side effects.

**Public Interface:** `export async function extractViaFredBeans(pdfBytes: Buffer): Promise<ExtractionOutcome>`; `export const FRED_BEANS_SIGNATURES = ['Fred Beans Parts']`; `export const FRED_BEANS_VENDOR_SLUG = 'fred_beans_parts'`.

**Reconciliation rule (Python side, `scripts/extract_fred_beans.py`):** This layout prints FOUR separate money columns per row, classified by right-edge (`x1`) position: `charges` (x1 ≤ 320), `credits` (≤ 400), `amount_due` (≤ 500), `remit_amount_due` (everything beyond, up to 10,000) — the last two are running-balance/remittance-stub restatements, not new transaction amounts, and are deliberately NEVER used as the line amount. This project's single `amount` field is `charges` (positive) when populated, else `-credits` (negative, sign-flipped) when populated — never `amount_due`/`remit_amount_due`. A row only counts as a genuine line item if it has EXACTLY 2 "code" tokens (`^\d{2}$`) present (`len(codes) != 2` skips the row as non-line-item). Total is the printed `"BALANCE DUE"` value from the aging-totals row (the 6th of ≥6 numeric tokens on the row following the `"CURRENT ... BALANCE DUE"` label), falling back to the computed sum. **This is the vendor with the documented worst confirmed live failure**: Claude's generic vision path extracted 273 lines summing to $113,672.48 against a printed total of $23,986.36 (~4.7x inflation) by conflating all four money columns into one "amount" per row before this port was wired in.

**Error Behaviour:** Same subprocess error contract as the other wrappers.

**Known Fragility:** The 4-column right-edge classification (`MONEY_COLUMNS` thresholds 320/400/500/10000) is the single most consequential hardcoded boundary set among all 9 vendors, given the ~4.7x historical failure this exists to prevent — any layout shift moving these columns even modestly would silently misclassify `amount_due`/`remit_amount_due` values as `charges`/`credits` again, reintroducing the exact inflation bug this module was built to fix, with no runtime check comparing computed sum to a sanity bound. The `len(codes) != 2` row-detection gate is also a fragile heuristic — a genuine line item with only 1 or 3+ code-shaped tokens (e.g. from an OCR artifact or a slightly different row format) would be silently dropped, not flagged.

**Change Impact:** Registered in `knownVendorExtractors.ts` (M-031). Given the documented severity of the failure this replaces, any regression here is a high-priority correctness risk, not just a reliability/cost one.

**Callers:** M-021 (via M-031's registry, dynamic dispatch — one of 9)
**Calls:** none (spawns `scripts/extract_fred_beans.py` as an external subprocess)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
