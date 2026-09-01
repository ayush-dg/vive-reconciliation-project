-- 008_exception_status.sqlite.sql — local SQLite equivalent of 008_exception_status.sql.
-- Adds a resolution workflow to recon.exception (Exceptions screen redesign,
-- 2026-09-01): until now no column tracked whether an exception had been looked at —
-- every exception was implicitly "open" forever. Nullable/defaulted so existing rows
-- (created before this migration) land as 'open', the correct interpretation for
-- anything not yet explicitly resolved/flagged/skipped.

ALTER TABLE recon_exception ADD COLUMN status TEXT NOT NULL DEFAULT 'open'
  CHECK (status IN ('open', 'resolved', 'flagged', 'skipped'));
ALTER TABLE recon_exception ADD COLUMN note TEXT NULL;
ALTER TABLE recon_exception ADD COLUMN resolved_at TEXT NULL;
