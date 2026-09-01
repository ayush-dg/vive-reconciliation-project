-- 008_exception_status.sql — Fabric-compatible T-SQL
-- Adds a resolution workflow to recon.exception (Exceptions screen redesign,
-- 2026-09-01): until now no column tracked whether an exception had been looked at —
-- every exception was implicitly "open" forever. Nullable/defaulted so existing rows
-- (created before this migration) land as 'open', the correct interpretation for
-- anything not yet explicitly resolved/flagged/skipped.

ALTER TABLE recon.exception ADD
  status NVARCHAR(20) NOT NULL CONSTRAINT DF_exception_status DEFAULT 'open'
    CONSTRAINT CK_exception_status CHECK (status IN ('open', 'resolved', 'flagged', 'skipped')),
  note NVARCHAR(MAX) NULL,
  resolved_at DATETIME2 NULL;
GO
