**Module:** Upload Page
**ID:** M-069
**Layer:** page
**Primary Responsibility:** Server-fetches the current document list and renders the Upload screen shell around `UploadForm`.

**Inputs (Props):** None.
**Outputs (Rendered UI + Side Effects):** Calls `listDocumentsWithStatusBadge()` (M-011) synchronously, renders a topbar ("Upload statement") and `<UploadForm initialDocuments={documents} />` (M-070). No other side effects.
**State Consumed:** None.
**Public Interface:** `export default function UploadPage()`.
**Error Behaviour:** No try/catch — a throw from M-011 propagates to `(app)/error.tsx` (M-066).
**Known Fragility:** Same non-async-despite-fetching-data pattern as M-067 (Home Page) — depends on `listDocumentsWithStatusBadge` remaining synchronous. Per its own comment, there is deliberately no Vendor field on this screen — vendor identification happens during extraction (Task 3.1), not at upload time; a future engineer "fixing" what looks like a missing form field would be reintroducing removed functionality against an explicit architecture decision (D-L amendment).
**Change Impact:** Changes to `ApiDocument` shape (M-011) affect what `UploadForm` (M-070) receives as `initialDocuments`.
**Callers:** Framework-invoked for route `/upload`; not imported elsewhere.
**Calls:** M-011 (`documents.ts` `listDocumentsWithStatusBadge`, page.tsx:9).
**Renders:** M-070 (UploadForm).
**Integration Points Used:** None (fetches internal API routes only) — N/A, calls a lib function directly server-side.
