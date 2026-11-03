-- 025_add_statement_pdf_edits.sql
--
-- One row per save from the in-app PDF editor (web/routers/statements.py). The
-- editor replaces the statement's SharePoint file in place, so SharePoint itself
-- shows the app's account as the editor: this table records who it really was.
--
-- new_document_hash is the SHA-256 of the saved (edited) PDF. Intake looks it up,
-- so an edited copy sent through the app again is reported as a duplicate of its
-- statement instead of becoming a new one (notebooks/01_document_intake.py).
-- Timestamps are ISO-8601 text in UTC, like jobs.submitted_at.
--
-- New and purely additive.

CREATE TABLE IF NOT EXISTS statement_pdf_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id TEXT NOT NULL,
    edited_by TEXT NOT NULL,
    edited_at TEXT NOT NULL,
    sharepoint_drive_id TEXT NOT NULL,
    sharepoint_item_id TEXT NOT NULL,
    old_etag TEXT,
    new_etag TEXT,
    old_size INTEGER,
    new_size INTEGER,
    new_document_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_statement_pdf_edits_statement ON statement_pdf_edits(statement_id);
CREATE INDEX IF NOT EXISTS idx_statement_pdf_edits_hash ON statement_pdf_edits(new_document_hash);
