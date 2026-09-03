**Module:** ExceptionsVendorListView
**ID:** M-072
**Layer:** component
**Primary Responsibility:** Client-side searchable, refreshable table of vendors with open exceptions, linking each to its per-vendor detail screen.

**Inputs (Props):** `{ initial: VendorExceptionSummary[] }` (type from `@/lib/exceptionsList`, out-of-scope M-019).
**Outputs (Rendered UI + Side Effects):** Renders a topbar ("Exceptions"), a search input (client-side substring filter on `vendorSlug`, case-insensitive) + Refresh button, and a table (Vendor / Missing in ERP / Amount mismatch / Resolved-with-progress-bar columns). Vendor name displayed via `humanizeVendorSlug(v.vendorSlug)` (M-010); link target uses the raw `vendorSlug` (`encodeURIComponent`), not the humanized label. `refresh()`: `GET /api/exceptions` (M-048), replaces `vendors` state.
**State Consumed:** None from shared stores — `vendors`, `search`, `loading`, `loadError` are all local `useState`, seeded from the `initial` prop.
**Public Interface:** `export default function ExceptionsVendorListView({ initial }: { initial: VendorExceptionSummary[] })`.
**Error Behaviour:** `refresh()` never throws — non-ok response or network exception sets `loadError`, rendering `<InlineLoadError onRetry={refresh} />` (M-081).
**Known Fragility:** Search filtering is purely client-side over whatever `vendors` currently holds (either the server-rendered `initial` or the last `refresh()` result) — there is no server-side search/pagination, so this assumes the vendor-with-exceptions list stays small enough to ship in full on every load. Empty-state message differs by whether a search is active ("No matching vendors" vs. "No exceptions — all statements reconciled cleanly") — a future engineer changing the search-clear behavior should verify both states still make sense.
**Change Impact:** Changes to `VendorExceptionSummary` shape (M-019) or to `/api/exceptions`'s (M-048) response shape break this view. Changes to `humanizeVendorSlug` (M-010) affect displayed vendor names here and in M-074, M-076.
**Callers:** M-071 (ExceptionsPage) renders this.
**Calls:** fetch `GET /api/exceptions` (line 18, → M-048); M-010 (`vendorDisplay.ts` `humanizeVendorSlug`, line 86).
**Renders:** M-081 (InlineLoadError, conditional on `loadError`).
**Integration Points Used:** None (fetches internal API routes only).
