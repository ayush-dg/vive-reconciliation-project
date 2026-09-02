**Module:** documents.ts
**ID:** M-011
**Layer:** serving
**Primary Responsibility:** Document registration (upload dedup via SHA-256 content hash), listing, and lookup against `extracted_document` — including the snake_case `ApiDocument` wire projection consumed by the Upload/Home UI.

**Inputs:**
- `findDocumentByHash(contentSha256: string)` — hex hash string, caller-supplied.
- `registerDocument(fileBytes: Buffer, legalEntityId: string, originalFilename: string | null = null)` — raw uploaded PDF bytes; `legalEntityId` trusted as already-validated by the caller (route layer); `originalFilename` optional, best-effort display metadata only (not part of the dedup identity key).
- `resolveVendorSlug(vendorId: string | null)` — nullable UUID.
- `getOpenExceptionCount(documentId: string)` — string id.
- `toApiDocument(doc: DocumentRow, statusBadge: {badge,label}, openExceptionCount: number)` — pre-computed values passed in, not fetched internally.
- `listDocumentsWithStatusBadge()` / `listDocuments()` — no parameters.
- `getDocumentById(documentId: string)` — string id.
No input validation is performed inside this module beyond `assertSqliteMode()`; all other inputs are trusted as pre-validated by callers.

**Outputs:** `registerDocument` INSERTs a new `extracted_document` row (non-duplicate path) and calls `saveDocumentFile` (M-005) to persist the PDF bytes as a side effect. All other functions are read-only. Returns `DocumentRow` / `RegisterResult` / `ApiDocument` shaped objects.

**Public Interface:**
- `export type DocumentRow`
- `export type RegisterResult = { document: DocumentRow; duplicate: boolean; legalEntityMismatch?: boolean }`
- `export type ApiDocument`
- `export function findDocumentByHash(contentSha256: string): DocumentRow | null`
- `export function registerDocument(fileBytes: Buffer, legalEntityId: string, originalFilename?: string | null): RegisterResult`
- `export function listDocuments(): DocumentRow[]`
- `export function resolveVendorSlug(vendorId: string | null): string | null`
- `export function getOpenExceptionCount(documentId: string): number`
- `export function toApiDocument(doc: DocumentRow, statusBadge: {badge:string;label:string}, openExceptionCount: number): ApiDocument`
- `export function listDocumentsWithStatusBadge(): ApiDocument[]`
- `export function getDocumentById(documentId: string): DocumentRow | null`

**Error Behaviour:** `assertSqliteMode()` throws a plain `Error` (uncaught here) if `getDbMode() !== 'sqlite'`, propagating to the caller. `registerDocument` wraps its INSERT in try/catch specifically for the check-then-insert race (a concurrent duplicate registration under multi-instance App Service): only errors matching `/UNIQUE constraint failed/i` against `err.message` are swallowed and converted into a graceful duplicate `RegisterResult`; any other error during the INSERT is rethrown uncaught. Every other function (`findDocumentByHash`, `listDocuments`, `resolveVendorSlug`, `getOpenExceptionCount`, `getDocumentById`, `listDocumentsWithStatusBadge`) has no try/catch — a DB error propagates directly to the caller uncaught.

**Known Fragility:**
- The UNIQUE-violation detection is a string match on `err.message` text (`/UNIQUE constraint failed/i`) — if the SQLite driver's error wording ever changes, this silently stops catching the intended race and the concurrent-duplicate path becomes an unhandled error instead of a graceful response.
- `resolveVendorSlug` lives here (not in `documentDetail.ts`) specifically to avoid a reverse-dependency cycle, since `documentDetail.ts` already depends on this module — moving it elsewhere risks reintroducing that cycle.
- `listDocuments`' `ORDER BY upload_timestamp DESC, rowid DESC` relies on SQLite's implicit `rowid` (only present because `document_id` is TEXT, not an INTEGER PRIMARY KEY) as the tiebreaker for `upload_timestamp`'s whole-second resolution — an incidental SQLite behavior that would silently regress to arbitrary tie ordering if the schema ever adds an explicit INTEGER PRIMARY KEY.
- `listDocumentsWithStatusBadge()` calls `computeDocumentStatus` (M-012) once per document in an unbatched loop — each call issues several separate queries — an N+1-style latent scaling fragility at larger document counts.
- The `status` vs `status_badge` conflation on `ApiDocument` was a previously-fixed real defect (documented in-file) — reintroducing raw `status` for display anywhere would reintroduce that bug.

**Change Impact:** M-013 and M-014 depend directly on this module's exports (`getDocumentById`/`resolveVendorSlug`, and `listDocumentsWithStatusBadge` respectively) — a signature or behavior change here propagates to the Document Detail and Home screens. M-044 is the direct API-route consumer for upload/list. M-067 and M-069 call into this module for SSR initial render. Changing `DocumentRow` or `ApiDocument`'s shape breaks all of these transitively, including the client-rendered `HomeView`/`UploadForm` components that parse the resulting JSON.

**Callers:** M-013, M-014, M-044, M-067, M-069
**Calls:** M-003, M-005, M-012
**Integration Points Used:** None (routes through M-003)
