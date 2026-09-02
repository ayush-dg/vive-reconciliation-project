**Module:** deterministicMatching
**ID:** M-026
**Layer:** pipeline
**Primary Responsibility:** Deterministic SQL-based matching of a Silver statement line to NetSuite's `bronze.netsuite_vendorbill` (or `vendorcredit`) by invoice/document number, with a local-fixture fallback when Fabric isn't configured; writes `recon.match` for resolved matches.

**Inputs:**
- `matchStatementLine(line: { normalizedInvoiceRef: string | null; amount: number; vendorSlug: string | null })` — the line to match.
- `writeMatch(statementLineId: string, reference: ReferenceCapture)` — the resolved reference to persist.
- Reads either the live Fabric Lakehouse (`bronze.netsuite_vendorbill`/`vendorcredit`, via `fabricLakehouse.ts`, when `isFabricLakehouseConfigured()`) or the local SQLite fixture tables `bronze_netsuite_vendorbill` (no local fixture for `vendorcredit` — credit-memo matches are Fabric-only).
- `writeMatch` requires SQLite mode (`assertSqliteMode()`); the read path (`matchStatementLine`) does NOT require SQLite mode — it can run against live Fabric regardless of `getDbMode()`.

**Outputs:**
- `matchStatementLine` returns `MatchOutcome` (no side effects — pure read).
- `writeMatch`: `INSERT INTO recon_match (match_id, statement_line_id, reference_run_id, reference_extracted_at, reference_source_system)` — the only place `recon_match` is written from in this codebase (per its own doc comment).

**Public Interface:**
- `export async function matchStatementLine(line: { normalizedInvoiceRef: string | null; amount: number; vendorSlug: string | null }): Promise<MatchOutcome>`
- `export function writeMatch(statementLineId: string, reference: ReferenceCapture): void`
- `export type MatchOutcome = { stage: 'deterministic_match'; status: 'matched' | 'unmatched'; candidateIds: string[]; reasonCodes: string[]; evidence: Record<string, unknown>; requiresReview: boolean; reference: ReferenceCapture | null }`

**Error Behaviour:**
- Neither `matchStatementLine` nor its helpers (`findReferenceRowByDocNumber`, `findLatestReferenceWatermark`) catch anything — a Fabric network failure or SQL error propagates uncaught to the caller (`matchingPipeline.ts`, M-025, which itself does not catch it either — see M-025's "all-or-nothing" fragility note).
- `writeMatch` throws synchronously via `assertSqliteMode()` if not in SQLite mode — notably this means `writeMatch` cannot be called when running matching against a live-Fabric read in a non-SQLite `getDbMode()`, even though `matchStatementLine` itself can read from live Fabric independent of `getDbMode()`. Not reachable in the current architecture (SQLite is the only supported mode this session), but a future engineer enabling Fabric as `getDbMode()`'s primary mode would hit this asymmetry immediately.
- No `normalizedInvoiceRef` on the line: NOT an error — returns `status: 'unmatched', reasonCodes: ['NOT_POSTED']` defensively, documented as unreachable in practice since the validation gate (M-023) already guarantees invoice_ref/ro_number presence before Silver.

**Known Fragility:**
- Vendor-scoped lookup (`vendorNamePrefixFromSlug`) uses ONLY the first underscore-token of the vendor slug (e.g. "fred" from "fred_beans_ford_of_mechanicsburg") to scope the NetSuite lookup — this was a real 2026-08-31 bug fix for a cross-vendor `tranid` collision, but the single-token heuristic is itself fragile: a future vendor whose family name is genuinely two words in the slug's leading position (not documented as tested) could either be too broad (false-positive matches across an unrelated vendor sharing the same first token) or too narrow, depending on how the underlying data is actually named. The local SQLite fixture has NO vendor table to scope by at all — this vendor-scoping only ever applies to the live Fabric path; local test runs never exercise it.
- Credit-memo sign handling: NetSuite stores a vendor credit's total as a POSITIVE magnitude while the statement shows it as NEGATIVE — `compareAmount = ref.isCredit ? -ref.refAmount : ref.refAmount` flips the sign before comparing. Getting this backward (or a future vendor whose credit convention differs) would silently double the effective mismatch rather than fixing it.
- The local fixture's duplicate-`bill_document_number` tie-break is `ORDER BY ABS(amount - ?) ASC, _extracted_at DESC` (closest-amount-first) — explicitly NOT "most-recent-wins," which the module's own comment says was a confirmed real bug once cross-vendor `tranid` collisions were found. A future engineer "simplifying" this back to plain most-recent-wins would silently reintroduce that bug for the local/test path.
- `rawFields` is `null` for every local-fixture match (only 4 real columns exist there) but populated for live Fabric matches — any UI code assuming `rawFields` is always present for a `matched`/`AMOUNT_MISMATCH` outcome will break specifically in local/test mode, not in production, making this an easy gap to miss in testing.
- `AMOUNT_TOLERANCE = 0.01` is a hardcoded constant, not shared with `validationGate.ts`'s own separately-defined `ARITHMETIC_TOLERANCE = 0.01` — currently the same value by coincidence, not by shared reference; changing one without the other would silently desynchronize the two gates' tolerance.

**Change Impact:** `matchingPipeline.ts` (M-025) is the sole caller of both exports and destructures `MatchOutcome`'s exact field names. `fabricLakehouse.ts` (M-008) changes to `getReferenceRowByTranId`/`getCreditRowByTranId`/`getLatestReferenceWatermark` signatures break this module directly. This is the only module reaching IP-003 (Fabric Lakehouse `bronze`), via M-008.

**Callers:** M-025
**Calls:** M-003 (41,99,132,221), M-008 (84,86,94,126,127)
**Integration Points Used:** None directly (via M-008)
