-- 023_add_job_step_timing.sql
--
-- Where the time goes for each uploaded PDF: one row per pipeline step per job
-- (extraction, validation, writing extracted data, silver build, reconciliation,
-- NetSuite write-back, ...). The worker fills it from the "Step timing:" lines the
-- pipeline prints, ONLY while JOB_TIMING_LOG_ENABLED=true (off by default).
--
-- step_order is the order the pipeline printed the steps in. Two summary steps,
-- intake_total and fabric_pipeline_total, CONTAIN other steps: do not add them to
-- the others. Timestamps are ISO-8601 text in UTC, like jobs.submitted_at.
--
-- New and purely additive.

CREATE TABLE IF NOT EXISTS job_step_timing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    statement_id TEXT,
    pdf_filename TEXT,
    step TEXT NOT NULL,
    step_order INTEGER NOT NULL,
    seconds REAL NOT NULL,
    logged_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_step_timing_job ON job_step_timing(job_id);
