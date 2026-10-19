-- 020_add_netsuite_writeback_log.sql
--
-- Stores every NetSuite write-back run in the database instead of only in a
-- JSON file inside the container (those files are lost on a restart, which is
-- why a deployed run's log could not be read afterwards).
--
-- netsuite_writeback_run: one row per run for a statement -- when it ran, how
-- it ended and the counts. A run that failed as a whole (a planning or
-- connection error, not a single refused write) has outcome 'failed' and
-- carries the error and traceback.
--
-- netsuite_writeback_record: one row per invoice line of that run. Written
-- lines keep the fields that were sent and the values they replaced, so a
-- write can be undone without the file log. Lines that were not written keep
-- the reason (not in sandbox, reconciled by an earlier statement, ...).
--
-- Both tables are new and purely additive. Timestamps are ISO-8601 text in
-- UTC, like jobs.submitted_at. The JSON columns hold JSON text.

CREATE TABLE IF NOT EXISTS netsuite_writeback_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT UNIQUE NOT NULL,
    statement_id TEXT NOT NULL,
    job_id TEXT,
    source TEXT NOT NULL,
    sandbox TEXT,
    outcome TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    written INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    period_locked INTEGER NOT NULL DEFAULT 0,
    held_by_other INTEGER NOT NULL DEFAULT 0,
    not_written INTEGER NOT NULL DEFAULT 0,
    not_written_counts TEXT,
    error_type TEXT,
    error_message TEXT,
    error_traceback TEXT,
    log_path TEXT
);

CREATE INDEX IF NOT EXISTS idx_nswb_run_statement ON netsuite_writeback_run(statement_id, started_at);

CREATE TABLE IF NOT EXISTS netsuite_writeback_record (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    statement_id TEXT NOT NULL,
    invoice_number TEXT,
    statement_amount REAL,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT,
    record_type TEXT,
    record_id TEXT,
    detail TEXT,
    seconds REAL,
    fields_sent TEXT,
    previous_values TEXT
);

CREATE INDEX IF NOT EXISTS idx_nswb_record_run ON netsuite_writeback_record(run_id);

CREATE INDEX IF NOT EXISTS idx_nswb_record_statement ON netsuite_writeback_record(statement_id, invoice_number);
