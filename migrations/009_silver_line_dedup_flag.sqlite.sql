-- 009_silver_line_dedup_flag.sqlite.sql — local SQLite equivalent of
-- 009_silver_line_dedup_flag.sql.
-- Session 8, Task 8.5 — row-level duplicate detection (same vendor_id +
-- normalized_invoice_ref + amount seen more than once), distinct from G4's
-- existing whole-document content-hash idempotency. Engineer-directed design
-- choice (per Task 8.5's own open question): a detected duplicate is
-- FLAGGED but still written to Silver/reaches matching unchanged — this
-- column is purely an additional signal, never a gate, so it cannot change
-- reconciliation behavior for a document that would already write this row
-- today. Defaults to 0 — existing rows predate this column and are, by
-- definition, not flaggable retroactively (no historical comparison was run
-- against them).

ALTER TABLE silver_statement_line ADD COLUMN is_duplicate_line INTEGER NOT NULL DEFAULT 0;
