-- 002_auth_users.sqlite.sql — local SQLite equivalent of 002_auth_users.sql.
-- Single-schema table (recon_app_user), no cross-file FK concerns here.

CREATE TABLE IF NOT EXISTS recon_app_user (
  user_id         TEXT     NOT NULL PRIMARY KEY,
  username        TEXT     NOT NULL UNIQUE,
  password_hash   TEXT     NOT NULL,
  display_name    TEXT     NULL,
  created_at      TEXT     NOT NULL DEFAULT (datetime('now'))
);
