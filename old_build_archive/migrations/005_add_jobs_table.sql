-- 005_add_jobs_table.sql
-- Phase 3: Background job queue for PDF uploads (see web/worker.py). A row
-- here represents one queued PDF; the worker thread picks up PENDING rows,
-- runs them through the existing pipeline (scripts/run_full_pipeline.py)
-- as a subprocess, and records the outcome. statement_id/vendor_name are
-- filled in only once the pipeline actually determines them, so they stay
-- NULL until the job reaches COMPLETED (or forever, if it FAILED before
-- that point).

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT UNIQUE NOT NULL,
    pdf_filename TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    statement_id TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN
        ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')),
    submitted_by TEXT,
    submitted_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error_message TEXT,
    vendor_name TEXT
);

-- The worker polls for the oldest PENDING row every cycle (see
-- get_next_pending_job() in web/queries.py) — index the column it filters on.
CREATE INDEX IF NOT EXISTS idx_jobs_status_submitted ON jobs(status, submitted_at);
