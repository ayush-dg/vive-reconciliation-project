-- 006_add_job_claim_token.sql
-- Adds a claim_token to jobs, used by claim_next_pending_job() in
-- web/queries.py to atomically flip a PENDING row to PROCESSING and then
-- look up exactly which row it claimed. See web/worker.py: without this,
-- more than one worker process (e.g. two server instances left running at
-- once) can race the same PENDING job, or pick up two different jobs for
-- the same uploaded PDF and run them concurrently — both missing the
-- extraction cache the other is about to write.

ALTER TABLE jobs ADD COLUMN claim_token TEXT;
