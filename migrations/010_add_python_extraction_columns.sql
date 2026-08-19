-- 010_add_python_extraction_columns.sql
-- python-extraction-experiment branch only.
--
-- Adds raw_charges/raw_credits/raw_amount_due/raw_transaction_code to
-- Bronze, and charges/credits/amount_due/transaction_code to Silver and
-- both Gold tables the Reports UI reads from (gold_matched_invoices,
-- gold_exceptions) -- see src/extraction_experiments/python_library/
-- adapter.py, which populates these from the Fred Beans Parts pdfplumber
-- extractor instead of claude_sonnet_client.py for this experiment.
--
-- Purely additive: no existing column is dropped, renamed, or retyped, so
-- the pre-existing AI-extraction pipeline (which never sets these fields)
-- is unaffected -- every one of these columns is nullable and simply
-- stays NULL on any row that doesn't populate it.
--
-- Ground-truth rule (confirmed by the engineer, see notebooks/
-- 01_document_intake.py's write_to_bronze()/normalize_to_silver()):
-- Charges populates the outstanding_amount/amount "matching" role when
-- present; when Charges is blank, outstanding_amount stays blank rather
-- than falling back to Credits or Amount Due -- those are display-only
-- columns for this row, not usable for matching. That row is then routed
-- to gold_exceptions (EXTRACTION_INCOMPLETE) by the existing INV-04 gate,
-- same as any other vendor's missing-amount row.

ALTER TABLE bronze_vendor_statement_raw ADD COLUMN raw_charges TEXT;
ALTER TABLE bronze_vendor_statement_raw ADD COLUMN raw_credits TEXT;
ALTER TABLE bronze_vendor_statement_raw ADD COLUMN raw_amount_due TEXT;
ALTER TABLE bronze_vendor_statement_raw ADD COLUMN raw_transaction_code TEXT;

ALTER TABLE silver_reconciliation_standard ADD COLUMN charges REAL;
ALTER TABLE silver_reconciliation_standard ADD COLUMN credits REAL;
ALTER TABLE silver_reconciliation_standard ADD COLUMN amount_due REAL;
ALTER TABLE silver_reconciliation_standard ADD COLUMN transaction_code TEXT;

ALTER TABLE gold_matched_invoices ADD COLUMN charges REAL;
ALTER TABLE gold_matched_invoices ADD COLUMN credits REAL;
ALTER TABLE gold_matched_invoices ADD COLUMN amount_due REAL;
ALTER TABLE gold_matched_invoices ADD COLUMN transaction_code TEXT;

ALTER TABLE gold_exceptions ADD COLUMN charges REAL;
ALTER TABLE gold_exceptions ADD COLUMN credits REAL;
ALTER TABLE gold_exceptions ADD COLUMN amount_due REAL;
ALTER TABLE gold_exceptions ADD COLUMN transaction_code TEXT;
