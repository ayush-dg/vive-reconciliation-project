// Idempotent dev-user bootstrap. Not part of the Migrated-only data baseline
// (UI_SURFACE.md's "no Seeded component" is about business/statement data,
// not operational user accounts) — but no task anywhere provisions the first
// user account either, and Sign In is untestable without one. Flagged as a
// gap, not silently assumed resolved. Real production user provisioning
// (who creates accounts, how) is not decided anywhere in the signed-off docs.
//
// Run: npm run seed:users
// Credentials: SEED_USER_USERNAME / SEED_USER_PASSWORD env vars, or the
// documented dev defaults below.
import crypto from 'node:crypto';
import { getSqliteDb, getDbMode, closeDb } from '../src/lib/db.ts';
import { runMigrations } from '../src/lib/migrate.ts';
import { hashPassword } from '../src/lib/auth.ts';

const username = process.env.SEED_USER_USERNAME ?? 'dev.user';
const password = process.env.SEED_USER_PASSWORD ?? 'DevOnly-ChangeMe-123';

if (getDbMode() !== 'sqlite') {
  console.error(
    'seed_users.mjs only supports the local SQLite fallback (FABRIC_SQL_ENDPOINT is set).\n' +
      'No automated path exists yet to create/seed recon.app_user against a live Fabric database — ' +
      'apply migrations/002_auth_users.sql via sqlcmd first, then insert a user row manually ' +
      '(password_hash must be produced by src/lib/auth.ts\'s hashPassword(), not plaintext). ' +
      'Flagged as a known gap, not a supported workflow, in sessions/S01_VERIFICATION_RECORD.md Task 1.3.'
  );
  process.exit(1);
}

runMigrations();
const db = getSqliteDb();

const existing = db.prepare('SELECT user_id FROM recon_app_user WHERE username = ?').get(username);
if (existing) {
  console.log(`User "${username}" already exists — no changes made.`);
} else {
  db.prepare(
    `INSERT INTO recon_app_user (user_id, username, password_hash, display_name) VALUES (?, ?, ?, ?)`
  ).run(crypto.randomUUID(), username, hashPassword(password), username);
  console.log(`Seeded dev user "${username}".`);
}

await closeDb();
