-- 011_add_version_tracking.sql
-- Adds version_number/previous_statement_id/is_latest_version to
-- bronze_vendor_statement_raw, silver_reconciliation_standard, and
-- gold_reconciliation_summary. gold_matched_invoices/gold_exceptions are
-- deliberately NOT touched -- they already join back to
-- gold_reconciliation_summary.statement_id, so "latest version only"
-- scoping there is a join, not a new column (see web/queries.py's
-- get_open_exceptions_count(), which now filters through
-- gold_reconciliation_summary.is_latest_version).
--
-- Replaces the fragile vendor_name + MAX(reconciliation_timestamp)
-- heuristic web/queries.py's _LATEST_RUN_PER_VENDOR used to determine
-- "the current row" for KPI purposes -- that heuristic could both
-- double-count (an AI-extracted vendor_name that varies slightly between
-- two uploads of the same statement, e.g. "asTech" vs. "asTech
-- (Repairify, Inc.)", looks like two different vendors and both get
-- summed) and under-count (it has no period awareness at all, so two
-- genuinely different periods for the same vendor can collapse to a
-- single "latest" row). version_number/previous_statement_id/
-- is_latest_version are instead set explicitly and deterministically at
-- intake time, keyed on vendor_id + statement_period (see
-- notebooks/01_document_intake.py's resolve_version_info()), not
-- inferred later from a timestamp/string heuristic.
--
-- Existing rows have no real prior-version history to link retroactively:
-- version_number=1, previous_statement_id=NULL, is_latest_version=1 for
-- all of them (SQLite has no native BOOLEAN; 0/1 matches this project's
-- existing convention, e.g. users.is_active).

ALTER TABLE bronze_vendor_statement_raw ADD COLUMN version_number INTEGER NOT NULL DEFAULT 1;
ALTER TABLE bronze_vendor_statement_raw ADD COLUMN previous_statement_id TEXT;
ALTER TABLE bronze_vendor_statement_raw ADD COLUMN is_latest_version INTEGER NOT NULL DEFAULT 1;

ALTER TABLE silver_reconciliation_standard ADD COLUMN version_number INTEGER NOT NULL DEFAULT 1;
ALTER TABLE silver_reconciliation_standard ADD COLUMN previous_statement_id TEXT;
ALTER TABLE silver_reconciliation_standard ADD COLUMN is_latest_version INTEGER NOT NULL DEFAULT 1;

ALTER TABLE gold_reconciliation_summary ADD COLUMN version_number INTEGER NOT NULL DEFAULT 1;
ALTER TABLE gold_reconciliation_summary ADD COLUMN previous_statement_id TEXT;
ALTER TABLE gold_reconciliation_summary ADD COLUMN is_latest_version INTEGER NOT NULL DEFAULT 1;
