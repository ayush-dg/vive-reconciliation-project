// Playwright global setup: ensures the local SQLite schema exists and a known
// test user is seeded before any spec runs. Test credentials are fixed here
// (not read from .env) so every spec file can rely on them without duplicating
// env-loading logic.
import crypto from 'node:crypto';
import { getSqliteDb, closeDb } from '../src/lib/db';
import { runMigrations } from '../src/lib/migrate';
import { hashPassword } from '../src/lib/auth';

export const TEST_USERNAME = 'testuser';
export const TEST_PASSWORD = 'TestPassword123!';
// A second, distinct named user (OD5: "multiple distinct named user accounts...
// not a single-shared-credential login") — exercised by sign-in.spec.ts so
// multi-user support is observed, not just asserted by schema shape.
export const TEST_USERNAME_2 = 'testuser2';
export const TEST_PASSWORD_2 = 'TestPassword456!';
export const TEST_SESSION_SECRET = 'playwright-test-session-secret-not-for-prod';

function seedUser(db: ReturnType<typeof getSqliteDb>, username: string, password: string, displayName: string) {
  const existing = db.prepare('SELECT user_id FROM recon_app_user WHERE username = ?').get(username);
  if (!existing) {
    db.prepare(
      `INSERT INTO recon_app_user (user_id, username, password_hash, display_name) VALUES (?, ?, ?, ?)`
    ).run(crypto.randomUUID(), username, hashPassword(password), displayName);
  }
}

export default async function globalSetup() {
  runMigrations();
  const db = getSqliteDb();
  seedUser(db, TEST_USERNAME, TEST_PASSWORD, 'Test User');
  seedUser(db, TEST_USERNAME_2, TEST_PASSWORD_2, 'Second Test User');
  await closeDb();
}
