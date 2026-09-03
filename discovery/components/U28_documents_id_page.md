**Module:** Document Detail Page
**ID:** M-075
**Layer:** page
**Primary Responsibility:** Server-fetches full detail for one document by id and renders the Document Detail screen, or throws (→ global error boundary) if the document doesn't exist.

**Inputs (Props):** `{ params: Promise<{ id: string }> }` — Next.js dynamic route param.
**Outputs (Rendered UI + Side Effects):** `await params`, calls `getDocumentDetail(id)` (M-013); if it returns falsy, **throws** `Error("Document not found: ${id}")`. Otherwise renders `<DocumentDetailView detail={detail} />` (M-076).
**State Consumed:** None.
**Public Interface:** `export default async function DocumentDetailPage({ params }: { params: Promise<{ id: string }> })`.
**Error Behaviour:** Explicit throw on not-found, per its comment, "so the global error boundary (error.tsx, 'per global default') renders the same inline message + Retry pattern this build uses everywhere, rather than a separate 404 page." Caught by `(app)/error.tsx` (M-066).
**Known Fragility:** Same generic-error-vs-not-found ambiguity as M-073 — a bad `id` (typo, deleted document, stale link) produces the identical "Something went wrong" UI as an unrelated render crash, with no distinguishing message. Depends on `getDocumentDetail` returning a falsy value (not throwing) for "not found" — if that lib function's contract ever changes to throw instead, the `if (!detail)` branch here becomes dead code and the thrown error's message changes.
**Change Impact:** Changes to `DocumentDetailData` shape (M-013) directly affect `DocumentDetailView` (M-076) props.
**Callers:** Framework-invoked for route `/documents/[id]`; linked to from M-068 (Home's vendor-slug link on each document row).
**Calls:** M-013 (`documentDetail.ts` `getDocumentDetail`, page.tsx:10).
**Renders:** M-076 (DocumentDetailView).
**Integration Points Used:** None (fetches internal API routes only) — N/A, calls a lib function server-side.
