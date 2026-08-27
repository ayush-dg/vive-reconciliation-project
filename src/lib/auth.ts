import crypto from 'node:crypto';
import { getDbMode, getSqliteDb, getFabricPool } from './db';

/**
 * Password hashing + user lookup (Task 1.3). Node-runtime only (server actions) —
 * not imported from src/middleware.ts, which runs on the Edge runtime; see
 * src/lib/session.ts for the Edge-safe session-token half of auth.
 */

const SCRYPT_KEYLEN = 64;

export function hashPassword(password: string): string {
  const salt = crypto.randomBytes(16).toString('hex');
  const hash = crypto.scryptSync(password, salt, SCRYPT_KEYLEN).toString('hex');
  return `${salt}:${hash}`;
}

export function verifyPassword(password: string, stored: string): boolean {
  const [salt, hashHex] = stored.split(':');
  if (!salt || !hashHex) return false;
  const candidate = crypto.scryptSync(password, salt, SCRYPT_KEYLEN);
  const expected = Buffer.from(hashHex, 'hex');
  if (candidate.length !== expected.length) return false;
  return crypto.timingSafeEqual(candidate, expected);
}

export type AppUser = {
  userId: string;
  username: string;
  passwordHash: string;
  displayName: string | null;
};

export async function findUserByUsername(username: string): Promise<AppUser | null> {
  const mode = getDbMode();
  if (mode === 'sqlite') {
    const db = getSqliteDb();
    const row = db
      .prepare(
        'SELECT user_id, username, password_hash, display_name FROM recon_app_user WHERE username = ?'
      )
      .get(username) as
      | { user_id: string; username: string; password_hash: string; display_name: string | null }
      | undefined;
    if (!row) return null;
    return {
      userId: row.user_id,
      username: row.username,
      passwordHash: row.password_hash,
      displayName: row.display_name,
    };
  }

  const pool = await getFabricPool();
  const result = await pool
    .request()
    .input('username', username)
    .query(
      'SELECT user_id, username, password_hash, display_name FROM recon.app_user WHERE username = @username'
    );
  const row = result.recordset[0];
  if (!row) return null;
  return {
    userId: row.user_id,
    username: row.username,
    passwordHash: row.password_hash,
    displayName: row.display_name,
  };
}
