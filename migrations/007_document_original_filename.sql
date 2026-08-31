-- 007_document_original_filename.sql — Fabric-compatible T-SQL
-- Upload screen shows the uploaded file's own name, not the extracted vendor (which is
-- frequently null while extraction is pending/failed and is a separate concept from what
-- file the user actually uploaded). Nullable — existing rows predate this column and have
-- no recoverable original filename (only content_sha256 was ever stored).

ALTER TABLE extracted.document ADD
  original_filename NVARCHAR(500) NULL;
GO
