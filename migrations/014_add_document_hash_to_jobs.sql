-- 014_add_document_hash_to_jobs.sql
--
-- Adds document_hash to jobs -- brings the local SQLite schema in line
-- with the live Azure SQL jobs table, which already carries this column
-- (see src/lakehouse/azure_sql_migrations.py). document_hash is stored on
-- the jobs row at completion time (web/queries.py's comment: "document_hash
-- (2026-09-03) lets _resolve_bronze_statement_id() find..."), letting a
-- cache-hit job recover its extracted data after a container restart
-- instead of relying on the local disk path still existing (see git
-- history: "Fix cache-hit jobs losing access to their extracted data on
-- container restart: store document_hash at completion time instead of
-- relying on local disk"). That fix landed only on Azure SQL directly,
-- with no matching numbered SQLite migration -- this file closes that
-- gap so a freshly-built local dev database doesn't fail with
-- "no such column: document_hash" the first time a job completes.
--
-- Purely additive: no existing column dropped, renamed, or retyped.

ALTER TABLE jobs ADD COLUMN document_hash TEXT;
