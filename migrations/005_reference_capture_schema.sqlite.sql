-- 005_reference_capture_schema.sqlite.sql — local SQLite equivalent of
-- 005_reference_capture_schema.sql. recon_match's swap (dropping snapshot_version,
-- adding 3 NOT NULL columns) is done via a clean drop/recreate rather than ALTER —
-- SQLite's ALTER TABLE ADD COLUMN requires a DEFAULT for NOT NULL columns even on an
-- empty table, and no real default exists for these three; recreating is simpler and the
-- table has no existing rows to lose (no session before this one has written to it).
-- recon_exception's new columns are nullable, so a plain ADD COLUMN is fine there.

DROP TABLE IF EXISTS recon_match;

CREATE TABLE recon_match (
  match_id                  TEXT     NOT NULL PRIMARY KEY,
  statement_line_id        TEXT     NOT NULL REFERENCES silver_statement_line(line_id),
  reference_run_id          TEXT     NOT NULL,
  reference_extracted_at    TEXT     NOT NULL,
  reference_source_system   TEXT     NOT NULL,
  created_at                TEXT     NOT NULL DEFAULT (datetime('now'))
);

ALTER TABLE recon_exception ADD COLUMN reference_run_id TEXT NULL;
ALTER TABLE recon_exception ADD COLUMN reference_extracted_at TEXT NULL;
ALTER TABLE recon_exception ADD COLUMN reference_source_system TEXT NULL;
-- Not in Task 1.2's original column list — UI_SURFACE.md's Exception Detail screen (v1.4)
-- reads recon.exception.evidence for the amount-mismatch drill-down and this build's own
-- extension, Task 5.3's CCC corroboration data (see sessions/S05_VERIFICATION_RECORD.md).
ALTER TABLE recon_exception ADD COLUMN evidence TEXT NULL;
