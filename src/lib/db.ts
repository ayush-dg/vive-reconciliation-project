import path from 'node:path';
import fs from 'node:fs';
import Database from 'better-sqlite3';
import sql from 'mssql';

/**
 * Environment-variable-driven database connection (Task 1.1).
 *
 * FABRIC_SQL_ENDPOINT set   -> connects to the live `recon` SQL database in Fabric.
 * FABRIC_SQL_ENDPOINT unset -> falls back to a local SQLite file, per Task 1.1's
 * resolved default. The fallback must never throw merely because the env var is
 * absent.
 */

export type DbMode = 'fabric' | 'sqlite';

export function getDbMode(): DbMode {
  return process.env.FABRIC_SQL_ENDPOINT ? 'fabric' : 'sqlite';
}

let sqliteInstance: Database.Database | null = null;

function getSqlitePath(): string {
  const configured = process.env.SQLITE_DB_PATH ?? './.data/recon.local.db';
  // Resolved against process.cwd(), which is the app root at runtime for both
  // `npm run dev`/`next start` locally and standard App Service deployments.
  // Launching the process from a different directory yields a different,
  // silently-created database — a known limitation of this local-dev-only path.
  // turbopackIgnore: this path is intentionally env-configurable, not a static
  // subfolder Next's output tracer can resolve at build time.
  return path.resolve(/* turbopackIgnore: true */ process.cwd(), configured);
}

export function getSqliteDb(): Database.Database {
  if (sqliteInstance) return sqliteInstance;

  const dbPath = getSqlitePath();
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });

  sqliteInstance = new Database(dbPath);
  sqliteInstance.pragma('journal_mode = WAL');
  sqliteInstance.pragma('foreign_keys = ON');
  return sqliteInstance;
}

let fabricPoolPromise: Promise<sql.ConnectionPool> | null = null;

export function getFabricPool(): Promise<sql.ConnectionPool> {
  const endpoint = process.env.FABRIC_SQL_ENDPOINT;
  if (!endpoint) {
    throw new Error(
      'getFabricPool() called without FABRIC_SQL_ENDPOINT set — check getDbMode() first.'
    );
  }
  if (!fabricPoolPromise) {
    fabricPoolPromise = new sql.ConnectionPool(endpoint).connect();
  }
  return fabricPoolPromise;
}

/**
 * Lightweight connectivity check used at app boot and by verification scripts.
 * Never throws on a merely-unset FABRIC_SQL_ENDPOINT — that is the resolved
 * fallback behaviour, not a failure.
 */
export async function pingDb(): Promise<{ mode: DbMode; ok: boolean }> {
  const mode = getDbMode();
  if (mode === 'sqlite') {
    const db = getSqliteDb();
    db.prepare('SELECT 1').get();
    return { mode, ok: true };
  }
  const pool = await getFabricPool();
  await pool.request().query('SELECT 1 AS ok');
  return { mode, ok: true };
}

/** Releases the active connection handle. Used by short-lived scripts (e.g.
 * verification checks) that need to exit cleanly rather than hold an open
 * file lock or socket. */
export async function closeDb(): Promise<void> {
  if (sqliteInstance) {
    sqliteInstance.close();
    sqliteInstance = null;
  }
  if (fabricPoolPromise) {
    const pool = await fabricPoolPromise;
    await pool.close();
    fabricPoolPromise = null;
  }
}
