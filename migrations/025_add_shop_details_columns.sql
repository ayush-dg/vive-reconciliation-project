-- 025_add_shop_details_columns.sql
--
-- Adds the extracted customer location and the matched VIVE shop's details to
-- document_intake_log. src/validation/location_lookup.py maps the customer
-- location extracted from a statement onto a shop in config/vive_shops.json;
-- billing_location (migration 017) now holds that shop's canonical name, and
-- these columns keep what came in and the shop's details from the list:
--
--   billing_location_extracted  what extraction returned for the customer
--                               location, before mapping (billing_location
--                               is overwritten by the mapped shop name)
--   shop_phone                  the shop's phone as printed in the list,
--                               e.g. "(207) 282-6860" ("" when the list has
--                               none for that shop)
--   shop_city                   the shop's city
--   shop_state                  the shop's state, e.g. "ME"
--
-- shop_* are NULL when the location was not mapped to a shop
-- (billing_location_source "unmapped" / "ambiguous" / "conflict"); all four
-- are NULL for any statement written before this migration.
--
-- Purely additive: no existing column dropped, renamed, or retyped.

ALTER TABLE document_intake_log ADD COLUMN billing_location_extracted TEXT;
ALTER TABLE document_intake_log ADD COLUMN shop_phone TEXT;
ALTER TABLE document_intake_log ADD COLUMN shop_city TEXT;
ALTER TABLE document_intake_log ADD COLUMN shop_state TEXT;
