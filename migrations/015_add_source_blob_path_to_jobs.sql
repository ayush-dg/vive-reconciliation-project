-- 015_add_source_blob_path_to_jobs.sql
--
-- Adds source_blob_path to jobs -- the blob path (relative to the 'raw'
-- container) a job's PDF was downloaded from, when it came from the
-- "Sync to Webapp" mailbox-ingest button rather than a manual upload.
--
-- NULL for every job that doesn't have a blob origin: manual uploads
-- (web/routers/upload.py) go straight from the browser to sample_data/
-- with no blob involved at all, and the existing dropzone-watcher/
-- Event-Grid paths already download-then-forget their source blob. Only
-- the new mailbox-ingest path (web/routers/mailbox_sync.py) populates
-- this column, so web/worker.py can write a job's outcome back onto its
-- originating blob's metadata (extraction_status/attempt_count/
-- last_error) when the job finishes -- skipped entirely when this column
-- is NULL, since there's nothing to write back to.
--
-- Purely additive: no existing column dropped, renamed, or retyped.

ALTER TABLE jobs ADD COLUMN source_blob_path TEXT;
