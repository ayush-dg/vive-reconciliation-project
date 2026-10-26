-- 023_add_job_recovery_columns.sql
--
-- Restart recovery for jobs (2026-10-26; design backups/fix_f1_20261025/restart_recovery_4d.md), used
-- only when VIVE_JOB_RECOVERY_ENABLED=true (web/queries.py job_recovery_enabled()):
--   claimed_by    which worker (host instance + boot) holds the job
--   heartbeat_at  when that worker last showed it is still running the job (every 60 s)
--   attempts      how many times the job has been claimed (capped at 2 -- JOB_MAX_ATTEMPTS)
--   attempt_log   one line per attempt that did not finish: why it was retried or abandoned
--
-- Purely additive: no existing column dropped, renamed, or retyped. NULL / 0 on every existing row.

ALTER TABLE jobs ADD COLUMN claimed_by TEXT;
ALTER TABLE jobs ADD COLUMN heartbeat_at TEXT;
ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN attempt_log TEXT;
