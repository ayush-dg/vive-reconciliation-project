-- 004_add_users_table.sql
-- Phase 3: Per-user logins, replacing the single hardcoded admin account
-- (see web/routers/auth.py). password_hash stores a bcrypt hash, never
-- plaintext. created_by records which user's session created the row
-- (NULL for the seed admin user, since nobody created it through the app).
--
-- The hardcoded admin/Vive@2026 fallback in web/routers/auth.py is kept
-- deliberately until database-backed users are confirmed working — see
-- that file's docstring.

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    created_by TEXT
);
