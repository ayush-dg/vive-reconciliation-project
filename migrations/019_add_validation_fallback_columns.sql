-- 019_add_validation_fallback_columns.sql
--
-- Arithmetic Validation Gate fallback chain (src/validation/
-- arithmetic_gate.py validate_with_fallbacks()). When the primary check
-- (printed total vs charges minus credits) fails, four alternative
-- identities are tried, each needing an exact 0.01 match from extracted
-- values: open_balance, statement_equation, running_balance,
-- section_subtotal. A fallback pass is still stored as
-- validation_status = 'matches'; these columns record HOW it matched.
--
-- document_intake_log:
--   validation_method       which check passed: 'primary', 'open_balance',
--                           'statement_equation', 'running_balance',
--                           'section_subtotal'; NULL when none passed (or
--                           for any row written before this migration).
--   validation_detail       JSON: every fallback attempted and why it
--                           passed or failed (e.g. the first broken row of
--                           a running-balance chain, guard failures).
--   previous_balance        the printed previous balance used by the
--                           statement_equation / running_balance checks --
--                           only stored once verified (src/validation/
--                           previous_balance.py).
--   previous_balance_source 'text_layer', 'model+text_layer',
--                           'model_label_only', or 'rejected: ...'.
--   section_totals          JSON list of printed section subtotals
--                           ({section, subtotal, invoice_count}).
--
-- bronze_vendor_statement_raw:
--   raw_unallocated         Autoly's "Unalloc." column (unapplied payment
--                           remainder), subtracted by the open_balance check.
--   raw_section             the printed section a row sits under, for the
--                           section_subtotal check.
--
-- Purely additive: no existing column dropped, renamed, or retyped.
-- validation_status gains two new values written by notebooks/
-- 01_document_intake.py: 'no_line_items' (a printed total but no extracted
-- rows) and 'not_a_statement' (no line-item table found at all). The
-- column is free text, so no schema change is needed for those.

ALTER TABLE document_intake_log ADD COLUMN validation_method TEXT;
ALTER TABLE document_intake_log ADD COLUMN validation_detail TEXT;
ALTER TABLE document_intake_log ADD COLUMN previous_balance REAL;
ALTER TABLE document_intake_log ADD COLUMN previous_balance_source TEXT;
ALTER TABLE document_intake_log ADD COLUMN section_totals TEXT;

ALTER TABLE bronze_vendor_statement_raw ADD COLUMN raw_unallocated TEXT;
ALTER TABLE bronze_vendor_statement_raw ADD COLUMN raw_section TEXT;
