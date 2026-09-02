**Module:** vendorIdentification
**ID:** M-021
**Layer:** pipeline
**Primary Responsibility:** Identifies the vendor for an uploaded document (known-vendor signature match, registry-slug match, or Claude-primary provisional creation), routes to the correct extractor, and runs S2 version-chaining once vendor/period are known.

**Inputs:**
- `documentId: string` — existing `extracted_document.document_id`, not validated against the DB before use (trusted caller-supplied).
- `legalEntityId: string` — used only for version-chaining's scoping query.
- `pdfBytes: Buffer` — raw PDF bytes, passed to `peekVendorSlug`, `extractViaPdfplumber`, `extractViaClaude`, `extractViaPdfplumberOcrFallback`, and each known-vendor extractor's subprocess.
- `forceFallback: boolean = false` — set by `extractionPipeline.ts`'s retry loop when attempt 1 was a genuine Claude failure; routes attempt 2 to the OCR/pdfplumber fallback tier instead of retrying Claude.
- Reads `extracted_vendor_registry` (SQLite only — `assertSqliteMode()` throws if `getDbMode() !== 'sqlite'`).

**Outputs:**
- Returns `IdentifyAndExtractResult { vendor: VendorRegistryRow | null; provider: 'python_library_pdfplumber' | 'claude_sonnet' | 'pdfplumber_fallback'; outcome: ExtractionOutcome }`.
- Side effect: on a resolved vendor, `UPDATE extracted_document SET vendor_id, statement_period WHERE document_id = ?`.
- Side effect: may `INSERT INTO extracted_vendor_registry` (provisional vendor via `createProvisionalVendor`, or known-vendor via `ensureKnownVendor`).
- Side effect: `ensureKnownVendor` unconditionally calls `ensureVendorStmtTable(vendorSlug)` (idempotent `CREATE TABLE IF NOT EXISTS` — see Known Fragility).
- Side effect: `runVersionChaining` may `UPDATE extracted_document` twice inside a transaction (flip `is_latest_version`, set `previous_statement_id`) when a same-vendor/period/entity document already exists.
- Does NOT write `extraction_attempt` — that remains `extractionPipeline.ts`'s job (write-before-validation ordering needs the outcome first).

**Public Interface:**
- `export async function identifyAndExtract(documentId: string, legalEntityId: string, pdfBytes: Buffer, forceFallback = false): Promise<IdentifyAndExtractResult>`
- `export type VendorRegistryRow = { vendorId: string; vendorSlug: string; tableName: string; extractionRoute: 'deterministic' | 'claude_primary' | null }`
- `export type IdentifyAndExtractResult = { vendor: VendorRegistryRow | null; provider: '...'; outcome: ExtractionOutcome }`

**Error Behaviour:**
- `assertSqliteMode()` throws synchronously if not in SQLite mode — propagates uncaught to the caller (`extractionPipeline.ts`, which wraps the whole `identifyAndExtract` call in try/catch and records the failure as an attempt with `rawOutput` = the error message).
- No vendor identifiable at all (`resolveProvisionalVendor` returns null): NOT thrown — `vendor` is returned `null`, `document.vendor_id`/`statement_period` stay NULL. This is intentional per G1/S10 (an attempt must still be recorded) and is caught downstream by the validation gate's `MISSING_IDENTIFIER` structural check.
- Extraction call failures (pdfplumber subprocess errors, Claude API errors) propagate as exceptions from `extractViaPdfplumber`/`extractViaClaude`/`extractViaPdfplumberOcrFallback`/known-vendor `.extract()` — not caught here, propagate to `extractionPipeline.ts`'s outer try/catch.
- `createProvisionalVendor` calls `assertValidVendorSlug` which throws on an invalid slug — uncaught here.

**Known Fragility:**
- [NOTABLE / historical bug, now fixed] `ensureKnownVendor` used to insert the registry row naming a `table_name` it never created — `extractionPipeline.ts`'s raw-row write (`INSERT INTO ${vendor.tableName} ...`, reachable only for `provider === 'python_library_pdfplumber'`) then threw AFTER the attempt row was already committed but BEFORE Silver normalization ran, leaving a document showing "Extracted" with zero `silver_statement_line` rows. **Verified as of this read: the fix IS correctly wired** — `ensureKnownVendor` (line 117) now calls `await ensureVendorStmtTable(vendorSlug)` unconditionally, before checking `findVendorBySlug`, so a registry row that was already created by the pre-fix broken code path gets its table repaired on next sight rather than skipped. Confirmed `ensureVendorStmtTable` (`src/lib/vendorSchema.ts:55`) is idempotent (`CREATE TABLE IF NOT EXISTS` in SQLite mode). A future engineer moving this call to only the "insert new registry row" branch would silently reintroduce the exact bug.
- `slugify()` collapses punctuation/case differences ("A&B Co" vs "A B Co" both → same slug) — a known, accepted limitation, not a bug, but a future engineer adding a second vendor with a name differing only in punctuation would silently merge them into one vendor.
- The known-vendor signature match (`findKnownVendorExtractor(pdfText)`) is checked BEFORE the generic `guessedSlug`/`matched` path and can override `matched` even when a registry row already matched a different route — order-dependent; reordering these branches changes routing outcomes.
- `peekVendorSlug` always uses `extractViaPdfplumber` (not the actually-routed extractor) purely as a cheap text scan — a future engineer might assume the peek reflects the real extraction provider, but it never does, even on the known-vendor or Claude path.
- The version-chaining query matches on `vendor_id + statement_period + legal_entity_id` with an exact string equality on `statement_period` — two documents whose statement periods differ only in formatting (e.g. "July 2026" vs "07/2026") will NOT be chained, silently creating disconnected duplicate documents.

**Change Impact:** Both `extractionPipeline.ts` (M-022, the sole caller) and every known-vendor extractor wrapper (M-032–M-040, invoked here) plus `pdfplumberExtractor.ts` (M-029), `pdfplumberOcrFallback.ts` (M-030), `aiProvider.ts` (M-028), and `knownVendorExtractors.ts`'s registry (M-031) are all coupled to this module's routing/return contract. Changing `IdentifyAndExtractResult`'s shape breaks `extractionPipeline.ts`'s attempt-row write. Changing routing order changes which provider processes a document, with direct cost (Claude billing) and correctness (per-vendor column logic) implications.

**Callers:** M-022
**Calls:** M-003, M-029, M-006, M-041, M-031, {M-032, M-033, M-034, M-035, M-036, M-037, M-038, M-039, M-040} (dynamic dispatch, one of 9, via M-031's registry), M-030, M-028
**Integration Points Used:** None (routes through M-003 or another pipeline module)
