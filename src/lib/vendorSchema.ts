import { getDbMode, getFabricPool, getSqliteDb } from './db';
import { vendorStmtTableName } from './schema';

/**
 * Per-vendor raw-table generator/template (Task 1.2). No vendors are known or
 * seeded at migration time (data baseline = Migrated only, no Seeded component,
 * per UI_SURFACE.md sign-off) — concrete extracted.stmt_<vendor_slug> tables are
 * created at runtime, once a real vendor is registered (Task 3.1's vendor
 * identification), not by the foundation migration.
 *
 * Same G1/S10 discipline as extracted.extraction_attempt: append-only, no
 * application-layer UPDATE path, enforced via trigger.
 */

function vendorStmtTableDdlFabric(vendorSlug: string): string {
  const table = vendorStmtTableName(vendorSlug, 'fabric');
  const triggerName = `extracted.trg_stmt_${vendorSlug}_no_update`;
  return `
CREATE TABLE ${table} (
  row_id       NVARCHAR(36)   NOT NULL PRIMARY KEY,
  document_id  NVARCHAR(36)   NOT NULL REFERENCES extracted.document(document_id),
  raw_row      NVARCHAR(MAX)  NOT NULL,
  created_at   DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE TRIGGER ${triggerName}
ON ${table}
AFTER UPDATE
AS
BEGIN
  RAISERROR('${table} is append-only; UPDATE is not permitted.', 16, 1);
  ROLLBACK TRANSACTION;
END;
`.trim();
}

function vendorStmtTableDdlSqlite(vendorSlug: string): string {
  const table = vendorStmtTableName(vendorSlug, 'sqlite');
  const triggerName = `trg_${table}_no_update`;
  return `
CREATE TABLE IF NOT EXISTS ${table} (
  row_id       TEXT     NOT NULL PRIMARY KEY,
  document_id  TEXT     NOT NULL REFERENCES extracted_document(document_id),
  raw_row      TEXT     NOT NULL,
  created_at   TEXT     NOT NULL DEFAULT (datetime('now'))
);
CREATE TRIGGER IF NOT EXISTS ${triggerName}
BEFORE UPDATE ON ${table}
BEGIN
  SELECT RAISE(ABORT, '${table} is append-only; UPDATE is not permitted.');
END;
`.trim();
}

/** Idempotently creates the raw table (+ append-only trigger) for one vendor. */
export async function ensureVendorStmtTable(vendorSlug: string): Promise<string> {
  const mode = getDbMode();
  if (mode === 'sqlite') {
    const db = getSqliteDb();
    db.exec(vendorStmtTableDdlSqlite(vendorSlug));
    return vendorStmtTableName(vendorSlug, 'sqlite');
  }
  const pool = await getFabricPool();
  await pool.request().batch(vendorStmtTableDdlFabric(vendorSlug));
  return vendorStmtTableName(vendorSlug, 'fabric');
}
