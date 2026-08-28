-- 006_exception_reason_codes.sqlite.sql — local SQLite equivalent of
-- 006_exception_reason_codes.sql. No existing rows to backfill meaningfully (this table
-- has had real writes only since Task 5.2/5.4 this session) — the '[]' default is a
-- syntactic placeholder for SQLite's ALTER TABLE ADD COLUMN NOT NULL requirement, never
-- actually relied on since every writeException() call supplies its own value.

ALTER TABLE recon_exception ADD COLUMN reason_codes TEXT NOT NULL DEFAULT '[]';
