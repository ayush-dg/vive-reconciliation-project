import fs from 'node:fs';
import path from 'node:path';
import { getDbMode, getSqliteDb } from './db';

/**
 * Migration runner (Task 1.2). SQLite path applies migrations/*.sqlite.sql files
 * directly — idempotent via a _migrations bookkeeping table. Fabric path is
 * intentionally NOT executed by this runner: Task 1.2's own Verification Command
 * applies migrations/*.sql (the canonical Fabric T-SQL, using `GO` batch
 * separators sqlcmd understands) via `sqlcmd -i`, not application code. Re-
 * implementing a T-SQL batch client here would duplicate sqlcmd, not replace it.
 */

const MIGRATIONS_DIR = path.resolve(process.cwd(), 'migrations');

function listSqliteMigrations(): string[] {
  return fs
    .readdirSync(MIGRATIONS_DIR)
    .filter((f) => f.endsWith('.sqlite.sql'))
    .sort();
}

export function runMigrations(): { applied: string[]; skipped: string[] } {
  const mode = getDbMode();
  if (mode === 'fabric') {
    throw new Error(
      'runMigrations() does not apply Fabric migrations — run `sqlcmd -S "$FABRIC_SQL_ENDPOINT" ' +
        '-d recon -i migrations/001_foundation_schema.sql` directly, per Task 1.2\'s Verification Command.'
    );
  }

  const db = getSqliteDb();
  db.exec(
    `CREATE TABLE IF NOT EXISTS _migrations (
       filename TEXT NOT NULL PRIMARY KEY,
       applied_at TEXT NOT NULL DEFAULT (datetime('now'))
     )`
  );

  const already = new Set(
    db.prepare('SELECT filename FROM _migrations').all().map((r) => (r as { filename: string }).filename)
  );

  const applied: string[] = [];
  const skipped: string[] = [];

  for (const filename of listSqliteMigrations()) {
    if (already.has(filename)) {
      skipped.push(filename);
      continue;
    }
    const sql = fs.readFileSync(path.join(MIGRATIONS_DIR, filename), 'utf8');
    const applyOne = db.transaction(() => {
      db.exec(sql);
      db.prepare('INSERT INTO _migrations (filename) VALUES (?)').run(filename);
    });
    applyOne();
    applied.push(filename);
  }

  return { applied, skipped };
}
