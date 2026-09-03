**Module:** storage.ts
**ID:** M-005
**Layer:** infra
**Primary Responsibility:** Local-filesystem, content-addressed storage for uploaded PDF document bytes, keyed by SHA-256 hash — an explicitly stated stand-in for a future Azure Blob store.

**Inputs:**
- `contentSha256: string`, `bytes: Buffer` (`saveDocumentFile`).
- `contentSha256: string` (`documentFileExists`, `readDocumentFile`).
- Env var `UPLOADS_DIR` (optional, default `./.data/uploads`), resolved against `process.cwd()`.

**Outputs:**
- `saveDocumentFile`: creates the uploads directory if absent (`fs.mkdirSync`), writes `${UPLOADS_DIR}/${contentSha256}.pdf` if it doesn't already exist (idempotent no-op on repeat), returns the resolved absolute file path.
- `documentFileExists`: returns `boolean`, no I/O mutation.
- `readDocumentFile`: returns the file's `Buffer` contents, no mutation.

**Public Interface:**
- `saveDocumentFile(contentSha256: string, bytes: Buffer): string`
- `documentFileExists(contentSha256: string): boolean`
- `readDocumentFile(contentSha256: string): Buffer`

**Error Behaviour:** No try/catch anywhere in the module. All `fs` calls are synchronous and any failure (permissions, disk full, missing file) propagates uncaught directly to the caller. `readDocumentFile` in particular throws `ENOENT` if called for a hash that was never saved — there is no existence check inside it (callers are expected to use `documentFileExists` first if needed).

**Known Fragility:**
- No validation that `contentSha256` actually matches a hash of `bytes` in `saveDocumentFile` — entirely caller-trusted. A caller passing a mismatched hash/bytes pair silently corrupts the content-addressing invariant with no detection here.
- The idempotency check (`if (!fs.existsSync(filePath))`) is not atomic — a TOCTOU race between two concurrent saves of the same hash is possible, though likely harmless since content should be identical for the same hash by construction.
- `contentSha256` is interpolated directly into a filesystem path with no format sanitization in this module — if a caller ever passed unsanitized/untrusted input as this parameter, it would be a path-traversal vector; currently mitigated purely by caller discipline (values expected to be real SHA-256 hex hashes), not enforced here.
- Local filesystem storage is explicitly a placeholder per the file's header comment ("required starting whenever a task actually needs it live — not yet") — any future migration to real blob storage would need `saveDocumentFile`'s return value (currently a raw filesystem path) redefined; any code that treats the return value as a local path rather than an opaque key would break.

**Change Impact:** Callers M-011 and M-022. A move to Azure Blob storage (the documented target) would change the semantics of the returned "path" for both callers and any other code that currently assumes local-file access patterns.

**Callers:** M-011, M-022
**Calls:** None
**Integration Points Used:** None (local disk only; not yet wired to Azure Blob despite the header comment naming it as the eventual target)
