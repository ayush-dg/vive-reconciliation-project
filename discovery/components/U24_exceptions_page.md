**Module:** Exceptions Page
**ID:** M-071
**Layer:** page
**Primary Responsibility:** Server-fetches the per-vendor exception summary list and renders the Exceptions landing screen.

**Inputs (Props):** None.
**Outputs (Rendered UI + Side Effects):** `async` server component; awaits nothing explicitly visible but is declared `async` — calls `listVendorsWithExceptions()` (M-019) and renders `<ExceptionsVendorListView initial={vendors} />` (M-072). No other side effects.
**State Consumed:** None.
**Public Interface:** `export default async function ExceptionsPage()`.
**Error Behaviour:** No try/catch — a throw from M-019 propagates to `(app)/error.tsx` (M-066).
**Known Fragility:** Per its own comment, this replaced an earlier "flat all-vendor list" design (2026-09-01 redesign) — now shows one row per vendor with ≥1 exception, drilling into `/exceptions/[vendorSlug]` (M-073) rather than a flat exception list. A future engineer unaware of this redesign history might reintroduce the old flat-list pattern elsewhere inconsistently.
**Change Impact:** Changes to `VendorExceptionSummary` shape (M-019) affect what `ExceptionsVendorListView` (M-072) can render.
**Callers:** Framework-invoked for route `/exceptions`; not imported elsewhere.
**Calls:** M-019 (`exceptionsList.ts` `listVendorsWithExceptions`, page.tsx:9).
**Renders:** M-072 (ExceptionsVendorListView).
**Integration Points Used:** None (fetches internal API routes only) — N/A, calls a lib function server-side.
