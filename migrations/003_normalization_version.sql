-- 003_normalization_version.sql — Fabric-compatible T-SQL
-- Task 3.6 (EXECUTION_PLAN.md Session 3): S6 requires every silver.statement_line
-- row to carry the normalization logic version that produced it, so historical
-- matching can identify which version was used. Not part of Task 1.2's original
-- column list — added here since Task 3.6 is the first task that actually writes
-- to this table.

ALTER TABLE silver.statement_line
  ADD normalization_version NVARCHAR(20) NOT NULL DEFAULT 'v1';
GO
