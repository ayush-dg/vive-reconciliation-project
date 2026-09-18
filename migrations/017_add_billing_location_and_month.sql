-- 017_add_billing_location_and_month.sql
--
-- Adds billing_location and statement_month to document_intake_log.
--
-- billing_location is a normalized "City, State" string (adapter.py's
-- _normalize_billing_location()) -- the vendor scripts already parse a
-- billing address into their summary dicts (billing_city/billing_state
-- separately, or a combined billing_city_state_zip string), but
-- adapter.py previously never pulled it out of that summary dict into
-- the returned schema, so it never reached this table. This pass wires
-- the pdfplumber path only; the Foundry path doesn't extract a billing
-- address at all yet (its EXTRACTION_PROMPT was never asked for one),
-- so this column is NULL for every claude_sonnet-routed row until that
-- follow-up is done.
--
-- statement_month is a canonical "YYYY-MM" string derived from whatever
-- raw statement_date either extraction path produced (src/validation/
-- date_utils.py's normalize_statement_month()) -- both paths already
-- extract SOME form of statement_date, but real data confirmed
-- inconsistent raw formats especially from the Foundry path
-- ('2026-08-31', '25AUG26', '07/31/2026' all seen for different
-- vendors), so this column holds the one normalized value both paths
-- can be displayed from consistently.
--
-- Purely additive: no existing column dropped, renamed, or retyped.

ALTER TABLE document_intake_log ADD COLUMN billing_location TEXT;
ALTER TABLE document_intake_log ADD COLUMN statement_month TEXT;
