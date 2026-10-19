-- 020_add_sharepoint_archive_columns.sql
--
-- SharePoint archive of each RECONCILIATION statement PDF (src/storage/
-- sharepoint_client.py, called from notebooks/01_document_intake.py
-- Step 8b). The NetSuite write-back links bills to sharepoint_web_url.
--
-- document_intake_log:
--   sharepoint_status       'uploaded' | 'existing' (same file already there)
--                           | 'failed' | 'skipped' (a setting missing while the
--                           feature flag is on); NULL = feature off / not eligible.
--   sharepoint_web_url      the file's SharePoint webUrl (NetSuite link target).
--   sharepoint_item_id      Graph driveItem id.
--   sharepoint_drive_id     Graph drive id of the library.
--   sharepoint_path         path inside the library.
--   sharepoint_error        short failure reason (never a secret or token).
--   sharepoint_uploaded_at  ISO-8601 UTC time of the attempt.
--
-- Purely additive. write_intake_log() carries these forward on re-intake of
-- the same file (same statement_id + same document_hash).

ALTER TABLE document_intake_log ADD COLUMN sharepoint_status TEXT;
ALTER TABLE document_intake_log ADD COLUMN sharepoint_web_url TEXT;
ALTER TABLE document_intake_log ADD COLUMN sharepoint_item_id TEXT;
ALTER TABLE document_intake_log ADD COLUMN sharepoint_drive_id TEXT;
ALTER TABLE document_intake_log ADD COLUMN sharepoint_path TEXT;
ALTER TABLE document_intake_log ADD COLUMN sharepoint_error TEXT;
ALTER TABLE document_intake_log ADD COLUMN sharepoint_uploaded_at TEXT;
