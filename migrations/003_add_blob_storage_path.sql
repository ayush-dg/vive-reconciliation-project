-- 003_add_blob_storage_path.sql
-- Phase 2: Object storage (Blob) -- see docs/VIVE_Implementation_Context.md
-- Section 4, Phase 2, "Object storage (Blob)".
--
-- Every processed vendor PDF is archived permanently in Azure Blob Storage
-- at {vendor_slug}/{yyyy}/{mm}/{document_hash}.pdf -- reusing the same
-- SHA-256 document_hash already computed for extraction caching (RULE-02),
-- so the same file is never stored twice. blob_storage_path links each
-- document_intake_log row to its archived blob. original_filename/
-- uploaded_by/uploaded_at are the human-facing metadata the doc calls for
-- alongside the blob path (vendor_name already exists on this table).

ALTER TABLE document_intake_log ADD COLUMN blob_storage_path TEXT;
ALTER TABLE document_intake_log ADD COLUMN original_filename TEXT;
ALTER TABLE document_intake_log ADD COLUMN uploaded_by TEXT;
ALTER TABLE document_intake_log ADD COLUMN uploaded_at TEXT;
