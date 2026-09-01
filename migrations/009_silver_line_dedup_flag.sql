-- 009_silver_line_dedup_flag.sql — Fabric-compatible T-SQL
-- Session 8, Task 8.5 — row-level duplicate detection (same vendor_id +
-- normalized_invoice_ref + amount seen more than once), distinct from G4's
-- existing whole-document content-hash idempotency. Engineer-directed design
-- choice (per Task 8.5's own open question): a detected duplicate is
-- FLAGGED but still written to Silver/reaches matching unchanged — this
-- column is purely an additional signal, never a gate.

ALTER TABLE silver.statement_line ADD
  is_duplicate_line BIT NOT NULL CONSTRAINT DF_statement_line_is_duplicate DEFAULT 0;
GO
