-- 006_exception_reason_codes.sql — Fabric-compatible T-SQL
-- Task 5.4 (challenge-review disposition): D-K's structured result contract
-- (stage/status/candidate_ids/reason_codes/evidence/confidence/requires_review) and this
-- task's own CC prompt ("sourcing category/reason_codes/evidence directly from each
-- stage's structured result... rather than re-deriving them") both name reason_codes
-- explicitly, but no column existed to persist it — every exception-producing stage
-- (Task 5.2's deterministic match, Task 5.3's residual pass) computes reason_codes and
-- they were silently dropped on the floor after being used once to derive `category`.

ALTER TABLE recon.exception ADD
  reason_codes NVARCHAR(MAX) NOT NULL DEFAULT '[]';
GO
