**Module:** exceptionsList.ts
**ID:** M-019
**Layer:** serving
**Primary Responsibility:** Vendor-grouped exceptions data for the two-pane Exceptions screen — a per-vendor summary list plus, per vendor, that vendor's full unpaginated exception list.

**Inputs:**
- `listVendorsWithExceptions()` — no parameters.
- `listExceptionsForVendor(vendorSlug: string)` — string param, no explicit validation (an unknown slug simply matches zero rows).

**Outputs:** Read-only, no writes.

**Public Interface:**
- `export type VendorExceptionSummary = { vendorSlug, total, resolvedCount, missingCount, mismatchCount, lastCreatedAt }`
- `export function listVendorsWithExceptions(): VendorExceptionSummary[]`
- `export type VendorExceptionRow = { exceptionId, invoiceRef, amount, category, status, createdAt, statementPeriod }`
- `export function listExceptionsForVendor(vendorSlug: string): VendorExceptionRow[]`

**Error Behaviour:** No try/catch in either function; `assertSqliteMode()` and any DB error propagate uncaught to the caller. An unknown/invalid `vendorSlug` passed to `listExceptionsForVendor` is not an error — it returns an empty array with no distinction between "vendor exists, zero exceptions" and "vendor slug doesn't exist at all."

**Known Fragility:**
- Vendors with a NULL `vendor_slug` are silently excluded from `listVendorsWithExceptions` (documented as rare, since `vendorIdentification.ts` resolves a provisional vendor for every line) — any exception belonging to such a vendor becomes permanently invisible on the Exceptions screen with no error or count signaling it exists; an increase in unresolved-vendor-identification cases would silently grow this invisible set.
- `listExceptionsForVendor` is deliberately unpaginated by design (documented assumption: realistic per-vendor counts stay in the dozens-to-low-hundreds) — no defensive `LIMIT` exists; a vendor that unexpectedly accumulates thousands of exceptions (e.g. a systemic upstream matching bug) returns an unbounded result set with no safety valve.
- `listVendorsWithExceptions`' `ORDER BY (resolvedCount = total) ASC` relies on SQLite's implicit boolean-as-integer coercion inside a numeric sort-key expression — a driver-specific idiom that would need rewriting if this module is ever ported to Fabric/T-SQL, which does not support boolean expressions as scalar sort keys the same way.

**Change Impact:** M-048, M-050, M-071, M-073 all depend on this module. M-071 (`exceptions/page.tsx`, SSR) and M-073 (`exceptions/[vendorSlug]/page.tsx`, SSR) call it directly for initial render; M-048/M-050 are the API routes the client-side `ExceptionsVendorListView` (M-072) and `ExceptionVendorDetailView` (M-074) components fetch from for refresh. A shape change to either exported type cascades to all four call sites and their downstream UI components.

**Callers:** M-048, M-050, M-071, M-073
**Calls:** M-003
**Integration Points Used:** None (routes through M-003)
