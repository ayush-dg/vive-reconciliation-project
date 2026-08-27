-- 002_auth_users.sql — Fabric-compatible T-SQL
-- Task 1.3 (EXECUTION_PLAN.md Session 1): Sign In screen needs a persisted user
-- store. No task in EXECUTION_PLAN.md explicitly creates one — Task 1.2's schema
-- list doesn't mention it, and OD5 (INVARIANTS.md) only resolves "multiple named
-- users share one role," not where those user records live. Flagged as a plan
-- gap (per pbvi_core.md's Loop rule: "if a task prompt conflicts with an
-- invariant, or something is not covered by the task prompt, do the minimum and
-- flag the gap"). This is the minimum needed for Task 1.3's own stated deliverable
-- (username/password sign-in for multiple named users) — not a user-management
-- screen (none exists in UI_SURFACE.md's Screen Inventory).

CREATE TABLE recon.app_user (
  user_id         NVARCHAR(36)   NOT NULL PRIMARY KEY,
  username        NVARCHAR(100)  NOT NULL UNIQUE,
  password_hash   NVARCHAR(200)  NOT NULL,
  display_name    NVARCHAR(200)  NULL,
  created_at      DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME()
);
GO
