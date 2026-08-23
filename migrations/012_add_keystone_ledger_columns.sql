-- 012_add_keystone_ledger_columns.sql
--
-- Adds raw_balance_forward/raw_period_activity/raw_credit_applied/
-- raw_payment_applied to Bronze -- Keystone Automotive Industries' four
-- ledger-style fields (see src/extraction/python_library/extract_keystone.py)
-- that have no existing column to reuse. Keystone's other four fields
-- reuse existing columns instead: reference_date -> raw_invoice_date,
-- reference_number -> raw_invoice_number, purchase_order_number ->
-- raw_po_number, balance_due -> raw_amount_due (see adapter.py's
-- "extract_keystone" _FIELD_MAP entry).
--
-- Bronze-only, deliberately. This is extraction/storage wiring only --
-- whether/how any of these four ledger fields should feed Silver's
-- outstanding_amount or the matching engine is an explicit, still-open
-- design decision (see the Keystone investigation session), not made by
-- this migration or by notebooks/01_document_intake.py's adapter wiring.
--
-- Purely additive: no existing column dropped, renamed, or retyped --
-- every one of the 9 other python-library vendors and every AI-extraction
-- row simply leaves these NULL.

ALTER TABLE bronze_vendor_statement_raw ADD COLUMN raw_balance_forward TEXT;
ALTER TABLE bronze_vendor_statement_raw ADD COLUMN raw_period_activity TEXT;
ALTER TABLE bronze_vendor_statement_raw ADD COLUMN raw_credit_applied TEXT;
ALTER TABLE bronze_vendor_statement_raw ADD COLUMN raw_payment_applied TEXT;
