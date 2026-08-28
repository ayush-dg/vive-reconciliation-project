-- 004_matching_lock.sqlite.sql — local SQLite equivalent of 004_matching_lock.sql.

CREATE TABLE IF NOT EXISTS recon_document_lock (
  document_id  TEXT     NOT NULL PRIMARY KEY
    REFERENCES extracted_document(document_id),
  acquired_at  TEXT     NOT NULL DEFAULT (datetime('now'))
);
