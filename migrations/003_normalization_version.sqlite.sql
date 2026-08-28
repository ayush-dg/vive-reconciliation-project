-- 003_normalization_version.sqlite.sql — local SQLite equivalent of
-- 003_normalization_version.sql. SQLite's ALTER TABLE ADD COLUMN syntax
-- (with a constant DEFAULT) is directly compatible here — no dialect fork
-- needed for this particular migration.

ALTER TABLE silver_statement_line
  ADD COLUMN normalization_version TEXT NOT NULL DEFAULT 'v1';
