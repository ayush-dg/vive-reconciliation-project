-- 007_add_batch_id_to_jobs.sql
-- Groups jobs created from the same Event Grid webhook delivery (see
-- web/routers/intake_trigger.py) so multiple files dropped into Blob
-- Storage at once can be tracked as one batch. NULL for manually
-- uploaded jobs, which have no batch concept.

ALTER TABLE jobs ADD COLUMN batch_id TEXT;
