**Module:** Exception Vendor Detail Page
**ID:** M-073
**Layer:** page
**Primary Responsibility:** Server-fetches a single vendor's exception rows and an optional preselected exception id from the query string, then renders the two-pane detail view.

**Inputs (Props):** `{ params: Promise<{ vendorSlug: string }>; searchParams: Promise<{ exception?: string }> }` — Next.js dynamic route params + optional `?exception=<id>` query param (used by Home's "Show exceptions →" link, per source comment).
**Outputs (Rendered UI + Side Effects):** `await params`/`await searchParams`, calls `listExceptionsForVendor(vendorSlug)` (M-019); if the result is an empty array, **throws** `Error("No exceptions found for vendor: ${vendorSlug}")` — deliberately, per its comment, using "the same 'let the global error boundary handle it' pattern the old detail page used" (i.e., no dedicated 404). Otherwise renders `<ExceptionVendorDetailView vendorSlug={vendorSlug} initialRows={rows} initialSelectedId={exception ?? null} />` (M-074).
**State Consumed:** None.
**Public Interface:** `export default async function ExceptionVendorDetailPage({ params, searchParams }: { params: Promise<{ vendorSlug: string }>; searchParams: Promise<{ exception?: string }> })`.
**Error Behaviour:** Explicitly throws on "no exceptions for this vendor" (covers both an invalid slug and a valid vendor whose exceptions all predate this vendor ever having one, per comment) — caught by `(app)/error.tsx` (M-066), showing the generic "Something went wrong" message rather than a vendor-specific "not found" message.
**Known Fragility:** `[NOTABLE]` A vendor that legitimately has zero *current* exceptions (e.g., all resolved) is indistinguishable at this layer from a nonexistent vendor slug — both produce the same thrown error and the same generic error-boundary UI, which could confuse a user following a stale bookmark/link to a vendor whose exceptions were all resolved after the link was shared. `?exception=` is passed through unvalidated as `initialSelectedId` — M-074 defensively checks it against `initialRows` before trusting it (`initialSelectedId && initialRows.some(...)`), so an invalid/stale id degrades gracefully there, not here.
**Change Impact:** Changes to `VendorExceptionRow` shape (M-019) affect `ExceptionVendorDetailView` (M-074) props. Changing the throw condition changes what counts as a "vendor not found" for the whole exceptions-detail flow, including links from Home (M-068).
**Callers:** Framework-invoked for route `/exceptions/[vendorSlug]`; also the destination of links from M-072 (vendor list) and M-068 (Home's "Show exceptions →").
**Calls:** M-019 (`exceptionsList.ts` `listExceptionsForVendor`, page.tsx:20).
**Renders:** M-074 (ExceptionVendorDetailView).
**Integration Points Used:** None (fetches internal API routes only) — N/A, calls a lib function server-side.
