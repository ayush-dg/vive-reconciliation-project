-- 004_matching_lock.sql — Fabric-compatible T-SQL
-- Task 5.1 (EXECUTION_PLAN.md Session 5): G5's processing-ownership lock for matching
-- invocation. A distinct lock dimension from Task 2.4's extraction lock
-- (extracted.document.status), since that column is permanently occupied once
-- extraction has run once — matching is a repeatable operation (a document can be
-- re-matched after a later correction/re-upload), so this lock is acquired and released
-- per invocation, not a one-way status flip. Lives in `recon` (not `extracted`) per G5's
-- own implementation note ("row lock in recon's Fabric SQL database").

CREATE TABLE recon.document_lock (
  document_id  NVARCHAR(36)   NOT NULL PRIMARY KEY
    REFERENCES extracted.document(document_id),
  acquired_at  DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME()
);
GO
