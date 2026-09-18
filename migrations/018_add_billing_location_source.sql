-- 018_add_billing_location_source.sql
--
-- Adds billing_location_source to document_intake_log -- tracks which
-- tier of the three-tier billing_location fallback (src/validation/
-- location_lookup.py's resolve_billing_location()) produced the value
-- in the existing billing_location column: "printed" (a genuinely
-- printed customer address, tier 1), "lookup_table" (a curated
-- shop-keyword match, tier 2), "shop_name_fallback" (a low-confidence
-- guess parsed out of the shop name itself, tier 3), or NULL (nothing
-- found at all, or any statement written before this migration).
--
-- Without this column, a fallback guess would be visually and
-- programmatically indistinguishable from a genuinely printed address
-- once stored in billing_location -- this exists so a reviewer (via
-- report_detail.html) or any downstream consumer can always tell which
-- tier produced a given value.
--
-- Purely additive: no existing column dropped, renamed, or retyped.

ALTER TABLE document_intake_log ADD COLUMN billing_location_source TEXT;
