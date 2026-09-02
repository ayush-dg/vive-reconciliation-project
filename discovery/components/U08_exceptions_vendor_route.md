**Module:** api/exceptions/vendor/[vendorSlug]/route.ts
**ID:** M-050
**Layer:** route
**Primary Responsibility:** Returns one vendor's full, unpaginated exception list for the two-pane Exception Vendor Detail view's left panel, and serves as that panel's post-action refresh endpoint.

**Inputs:** `GET(_request: Request, { params }: { params: Promise<{ vendorSlug: string }> })` — path param `vendorSlug` only; no query params, no body.
**Outputs:** 200 only: `{ rows: VendorExceptionRow[] }`, each row `{ exceptionId, invoiceRef: string|null, amount: number, category: string, status: string, createdAt: string, statementPeriod: string|null }` (per M-019's `listExceptionsForVendor`). No non-200 path — an unknown/nonexistent `vendorSlug` simply yields `{ rows: [] }` (the SQL `WHERE vr.vendor_slug = ?` matches nothing), not a 404.
**Public Interface:**
`export async function GET(_request: Request, { params }: { params: Promise<{ vendorSlug: string }> }): Promise<NextResponse>`
**Error Behaviour:** No try/catch. Any exception from `listExceptionsForVendor` (M-019) — e.g. non-SQLite mode — is unhandled -> 500.
**Known Fragility:** [NOTABLE] A nonexistent or misspelled `vendorSlug` returns 200 with an empty `rows` array rather than 404 — a future engineer building error handling in M-074 around this endpoint could mistake "no exceptions for this vendor" for "vendor doesn't exist" since both look identical on the wire. Per M-019's own comment, this list is intentionally unpaginated (`.all()`, no LIMIT/OFFSET) on the stated assumption that "a realistic per-vendor reconciliation run's exception count (dozens to low hundreds) never approaches a volume where that tradeoff matters" — if that assumption breaks (e.g. a vendor with thousands of exceptions), this route has no pagination mechanism to fall back on and would return the entire set in one response.
**Change Impact:** Refetched by M-074 after every resolve/flag/skip action (via M-049's PATCH) to keep the resolve-progress bar and filter-tab counts in sync — this route's response shape and ordering (open exceptions first, then by `createdAt DESC`, per M-019's SQL) directly drives that UI's default sort/grouping.
**Callers:** M-074 (ExceptionVendorDetailView.tsx, fetch)
**Calls:** M-019 (`src/app/api/exceptions/vendor/[vendorSlug]/route.ts:9`)
**Integration Points Used:** None (routes through serving-layer modules)
