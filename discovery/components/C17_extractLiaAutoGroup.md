**Module:** extractLiaAutoGroup
**ID:** M-037
**Layer:** pipeline
**Primary Responsibility:** Known-vendor deterministic extractor for Lia Auto Group — the first (Session 8, Task 8.1) real known-vendor extractor wired into this build. Spawns `scripts/extract_lia.py` as a subprocess and converts its JSON output into this project's `ExtractionOutcome`/`ExtractedStatement` shape.

**Inputs:** `extractViaLiaAutoGroup(pdfBytes: Buffer)`. Spawns `python scripts/extract_lia.py <tmpPath>`.

**Outputs:** Returns `ExtractionOutcome`. No DB writes; no other side effects.

**Public Interface:** `export async function extractViaLiaAutoGroup(pdfBytes: Buffer): Promise<ExtractionOutcome>`; `export const LIA_AUTO_GROUP_SIGNATURES = ['LIA AUTO GROUP', 'Lia Group Payables']`; `export const LIA_AUTO_GROUP_VENDOR_SLUG = 'lia_auto_group'`.

**Reconciliation rule (Python side, `scripts/extract_lia.py`):** Word-position row reconstruction with right-edge (x1) money classification into three columns: `purchases` (x1 ≤ 390), `payments_credits` (≤ 470), `balance` (everything else). Sums the **`balance`** column only — a purchase's balance is positive, a credit memo's is the negative of its `payments_credits` value; no separate charge/credit split is carried into this project's schema (unlike the reference implementation's own richer multi-field summary). Money values use a trailing-minus convention ("50.00-" → -50.00), parsed by `parse_money`. Total is the "PLEASE PAY THIS AMOUNT" figure from the last page's aging-summary row (located by finding the "PAST"/"DUE"/"CURRENT" label row and taking the 3rd money token from the row below it), falling back to the computed sum.

**Error Behaviour:** Same subprocess error contract as the other wrappers.

**Known Fragility:** `parse_aging_summary` locates the totals row by searching for a row containing ALL of the literal tokens "PAST", "DUE", "CURRENT" as separate words, then takes the 3rd sorted money token from within the next 2 rows — a reformatted aging-summary header (different word order, merged tokens, or fewer than 3 money values on the following rows) would silently return `None`, falling back to the computed total with no explicit warning that the printed total wasn't actually found and cross-checked. Since this was the FIRST vendor wired up (Session 8), other 8 wrappers' patterns (row-tolerance grouping, right-edge money classification, trailing-minus parsing) were directly copied from this one — a latent bug in this module's shared helper logic could be silently replicated across siblings that reused the same pattern rather than the same code.

**Change Impact:** Registered in `knownVendorExtractors.ts` (M-031). As the template other wrappers' logic patterns were modeled on, changes here for a "fix" may need cross-checking against `extractFredBeans.ts`/`extractQuirk.ts`/etc., which share structurally similar (but independently duplicated, not shared-function) parsing helpers.

**Callers:** M-021 (via M-031's registry, dynamic dispatch — one of 9)
**Calls:** none (spawns `scripts/extract_lia.py` as an external subprocess)
**Integration Points Used:** None (routes through M-003 or another pipeline module)
