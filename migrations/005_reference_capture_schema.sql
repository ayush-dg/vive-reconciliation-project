-- 005_reference_capture_schema.sql — Fabric-compatible T-SQL
-- Task 5.2 (EXECUTION_PLAN.md Session 5): S8 (amended 2026-08-28) replaces the original
-- snapshot_version column (Task 1.2's premise — this build stamping its own reference-data
-- version) with the three columns actually captured at match time from the externally-
-- owned NetSuite/CCC Lakehouse table's own audit columns (ARCHITECTURE.md D-M). No existing
-- rows are affected — no session before this one has written to recon.match/recon.exception.

ALTER TABLE recon.match DROP COLUMN snapshot_version;
GO

ALTER TABLE recon.match ADD
  reference_run_id          NVARCHAR(100)  NOT NULL,
  reference_extracted_at    DATETIME2      NOT NULL,
  reference_source_system   NVARCHAR(50)   NOT NULL;
GO

-- evidence: not in Task 1.2's original column list — added here since UI_SURFACE.md's
-- Exception Detail screen (v1.4) explicitly reads recon.exception.evidence for the
-- amount-mismatch drill-down and (this build's own extension, see
-- sessions/S05_VERIFICATION_RECORD.md) Task 5.3's CCC corroboration data. D-K's
-- structured result contract (stage/status/candidate_ids/reason_codes/evidence/
-- confidence/requires_review) needs somewhere to persist its evidence field for a later
-- screen to read back without a live re-query, per ARCHITECTURE.md D-M.
ALTER TABLE recon.exception ADD
  reference_run_id          NVARCHAR(100)  NULL,
  reference_extracted_at    DATETIME2      NULL,
  reference_source_system   NVARCHAR(50)   NULL,
  evidence                  NVARCHAR(MAX)  NULL;
GO
