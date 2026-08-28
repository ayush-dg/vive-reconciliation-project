import fs from 'node:fs';
import path from 'node:path';

/**
 * Environment-variable-driven file storage (Task 2.1/2.2), same pattern as
 * db.ts's DB connection: local filesystem fallback for Sessions 1-3, a real
 * blob store (Azure Blob, per ARCHITECTURE.md's target stack) required
 * starting whenever a task actually needs it live — not yet, in this session.
 */

function getUploadsDir(): string {
  const configured = process.env.UPLOADS_DIR ?? './.data/uploads';
  // turbopackIgnore: env-configurable, not a static subfolder the output
  // tracer can resolve at build time — same reasoning as db.ts's SQLite path.
  return path.resolve(/* turbopackIgnore: true */ process.cwd(), configured);
}

/** Stores a file's bytes under its content hash. Idempotent: writing the same
 * hash twice is a no-op on the second call (matches G4's dedup semantics —
 * the caller decides whether a duplicate is an error; this layer just avoids
 * a redundant disk write). */
export function saveDocumentFile(contentSha256: string, bytes: Buffer): string {
  const dir = getUploadsDir();
  fs.mkdirSync(dir, { recursive: true });
  const filePath = path.join(dir, `${contentSha256}.pdf`);
  if (!fs.existsSync(filePath)) {
    fs.writeFileSync(filePath, bytes);
  }
  return filePath;
}

export function documentFileExists(contentSha256: string): boolean {
  return fs.existsSync(path.join(getUploadsDir(), `${contentSha256}.pdf`));
}
