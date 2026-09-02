**Module:** api/exceptions/route.ts
**ID:** M-048
**Layer:** route
**Primary Responsibility:** Returns the Exceptions landing screen's data — one summary row per vendor that has at least one exception, used both as the initial data source and the refresh endpoint for that screen.

**Inputs:** `GET()` — no params, no query, no body.
**Outputs:** 200 only: `{ vendors: VendorExceptionSummary[] }`, where each row is `{ vendorSlug, total, resolvedCount, missingCount, mismatchCount, lastCreatedAt }` (per M-019's `listVendorsWithExceptions`). No non-200 path exists in this handler.
**Public Interface:**
`export async function GET(): Promise<NextResponse>`
**Error Behaviour:** No try/catch. Any exception from `listVendorsWithExceptions()` (M-019) — e.g. non-SQLite mode via `assertSqliteMode()`, or a DB error — is unhandled -> Next.js default 500. This route cannot return any 4xx by design (no inputs to validate).
**Known Fragility:** Per M-019's own doc comment, vendors with a NULL `vendor_slug` are silently excluded from the result — a statement whose vendor never resolved has exceptions that exist in the DB but are invisible on this screen, with no count or indicator that anything was omitted. This is described as rare in practice but is a genuine blind spot a future engineer debugging "missing exceptions" could easily overlook, since this route surfaces no signal that filtering happened. Per-vendor exception detail has moved to M-050 (`/api/exceptions/vendor/[vendorSlug]`) as of the 2026-09-01 redesign — this route no longer returns a flat, all-vendor exception list (a behavior change from an earlier version of this screen, per this route's own comment).
**Change Impact:** Sole data source for the Exceptions landing screen (M-071 SSR via M-019 directly, and M-072's client-side refresh via this route). Any change to `VendorExceptionSummary`'s shape in M-019 flows straight through to M-072's rendering (resolve-progress bars, filter-tab counts) with no transformation in this route.
**Callers:** M-072 (ExceptionsVendorListView.tsx, fetch)
**Calls:** M-019 (`src/app/api/exceptions/route.ts:8`)
**Integration Points Used:** None (routes through serving-layer modules)
