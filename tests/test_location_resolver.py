"""
tests/test_location_resolver.py

resolve_billing_location() (src/validation/location_lookup.py): maps an
extracted customer location onto a shop in config/vive_shops.json by name,
then phone, then city -- and says which one found it. A city shared by shops,
or two signals naming different shops, is never silently picked.

Synthetic inputs only; reads config/vive_shops.json, no network or database.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.validation import shop_list
from src.validation.location_lookup import apply_location, resolve_billing_location


class NameStep(unittest.TestCase):
    def test_shop_name_inside_the_customer_name(self):
        self.assertEqual(resolve_billing_location(None, "Coleman's Auto Body /POC"), ("Coleman's", "name_match"))
        self.assertEqual(resolve_billing_location(None, ["VIVE COLLISION- RP BELL"]), ("RP Bell", "name_match"))

    def test_apostrophes_and_case_do_not_matter(self):
        self.assertEqual(resolve_billing_location(None, "COLEMANS AUTO BODY"), ("Coleman's", "name_match"))

    def test_longest_name_wins(self):
        self.assertEqual(resolve_billing_location(None, "VIVE COLLISION - CLARKS SUMMIT")[0], "Clarks Summit")
        self.assertEqual(resolve_billing_location(None, "Prestige - NH")[0], "Prestige - NH")
        self.assertEqual(resolve_billing_location(None, "Noaker's Truck Shop")[0], "Noaker's Truck Shop")

    def test_a_name_must_be_a_whole_word(self):
        self.assertEqual(resolve_billing_location(None, "Modernization Inc")[1], "unmapped")

    def test_billing_location_that_is_a_shop_name(self):
        self.assertEqual(resolve_billing_location("Coleman's", None), ("Coleman's", "name_match"))

    def test_a_city_is_not_a_name_match(self):
        # "Bangor, ME" is shared by the Bangor and Maine Collision shops.
        self.assertEqual(resolve_billing_location("Bangor, ME", None), ("Bangor, ME", "unmapped"))


class PhoneStep(unittest.TestCase):
    def test_phone_finds_the_shop_when_the_name_does_not(self):
        self.assertEqual(resolve_billing_location("Mechanic Falls, ME", "Quirk Auto", phone="207-282-6860"),
                         ("RP Bell", "phone_match"))

    def test_phone_formats_are_normalized(self):
        for phone in ("(207) 282-6860", "1-207-282-6860", "2072826860"):
            with self.subTest(phone=phone):
                self.assertEqual(resolve_billing_location(None, None, phone=phone), ("RP Bell", "phone_match"))

    def test_an_unknown_phone_is_ignored(self):
        self.assertEqual(resolve_billing_location("Scarborough, ME", None, phone="207-000-0000"),
                         ("Scarborough, ME", "unmapped"))


class CityStep(unittest.TestCase):
    def test_one_shop_in_the_city(self):
        self.assertEqual(resolve_billing_location("Auburn, ME", None), ("Coleman's", "city_match"))
        self.assertEqual(resolve_billing_location("AUBURN ME", None), ("Coleman's", "city_match"))

    def test_the_state_picks_between_same_named_cities(self):
        self.assertEqual(resolve_billing_location("Manchester, NH", None)[0], "Prestige - NH")
        self.assertEqual(resolve_billing_location("Manchester, CT", None)[0], "Vernon")

    def test_a_city_with_two_shops_is_not_picked(self):
        self.assertEqual(resolve_billing_location("Bangor, ME", None)[1], "unmapped")

    def test_the_ship_to_address_maps_when_the_bill_to_is_not_a_shop_city(self):
        addresses = [{"city": "Mechanic Falls", "state": "ME"}, {"city": "Auburn", "state": "ME"}]
        self.assertEqual(resolve_billing_location("Mechanic Falls, ME", None, addresses=addresses),
                         ("Coleman's", "city_match"))

    def test_addresses_pointing_at_two_shops_are_not_picked(self):
        addresses = [{"city": "Auburn", "state": "ME"}, {"city": "Saco", "state": "ME"}]
        self.assertEqual(resolve_billing_location(None, None, addresses=addresses), (None, "unmapped"))


class Unmapped(unittest.TestCase):
    def test_an_unknown_location_keeps_its_extracted_value(self):
        self.assertEqual(resolve_billing_location("Scarborough, ME", None), ("Scarborough, ME", "unmapped"))

    def test_nothing_extracted(self):
        self.assertEqual(resolve_billing_location(None, None), (None, "unmapped"))
        self.assertEqual(resolve_billing_location("", []), (None, "unmapped"))

    def test_a_pdfplumber_style_input_with_only_a_shop_name(self):
        self.assertEqual(resolve_billing_location(None, ["VIVE COLLISION - CHERRY HILL (W60)"]),
                         ("Cherry Hill", "name_match"))


class Conflict(unittest.TestCase):
    def test_the_name_wins_over_a_phone_for_another_shop(self):
        # RP Bell by name, Coleman's by phone.
        self.assertEqual(resolve_billing_location("Scarborough, ME", "VIVE COLLISION - RP BELL", phone="(207) 784-6121"),
                         ("RP Bell", "name_match"))

    def test_the_name_wins_over_a_city_that_points_elsewhere(self):
        self.assertEqual(resolve_billing_location("Auburn, ME", "VIVE COLLISION - RP BELL"),
                         ("RP Bell", "name_match"))

    def test_without_a_name_address_signals_that_disagree_are_a_conflict(self):
        # Auburn's city is Coleman's; the phone is RP Bell's.
        self.assertEqual(resolve_billing_location("Auburn, ME", None, phone="(207) 282-6860")[1], "conflict")

    def test_signals_that_agree_are_not_a_conflict(self):
        self.assertEqual(resolve_billing_location("Auburn, ME", "Coleman's Auto Body", phone="(207) 784-6121"),
                         ("Coleman's", "name_match"))


class NameFamilies(unittest.TestCase):
    """Shops whose names start the same way: Middletown / Middletown - NJ,
    Prestige / Prestige - NH, Noaker's / Noaker's Truck Shop."""

    def test_the_longer_name_is_used_when_the_text_has_it(self):
        self.assertEqual(resolve_billing_location(None, "VIVE COLLISION - MIDDLETOWN NJ"),
                         ("Middletown - NJ", "name_match"))

    def test_the_state_picks_the_family_member(self):
        addresses = [{"label": "bill_to", "city": "Middletown", "state": "NJ"}]
        self.assertEqual(resolve_billing_location(None, "VIVE COLLISION - MIDDLETOWN", addresses=addresses),
                         ("Middletown - NJ", "name_match"))
        addresses = [{"label": "bill_to", "city": "Middletown", "state": "RI"}]
        self.assertEqual(resolve_billing_location("Middletown, RI", "VIVE COLLISION - MIDDLETOWN", addresses=addresses),
                         ("Middletown", "name_match"))

    def test_the_phone_picks_the_family_member(self):
        phone = shop_list.by_name("Middletown - NJ")["phone"]
        self.assertEqual(resolve_billing_location(None, "Middletown", phone=phone), ("Middletown - NJ", "name_match"))

    def test_the_city_of_an_address_picks_the_family_member(self):
        addresses = [{"label": "ship_to", "city": "Manchester", "state": "NH"}]
        self.assertEqual(resolve_billing_location(None, "Prestige", addresses=addresses),
                         ("Prestige - NH", "name_match"))

    def test_a_family_name_with_nothing_else_is_ambiguous(self):
        for text in ("VIVE COLLISION - MIDDLETOWN", "Prestige"):
            with self.subTest(text=text):
                self.assertEqual(resolve_billing_location(None, text), (None, "ambiguous"))

    def test_ambiguous_keeps_the_extracted_value(self):
        self.assertEqual(resolve_billing_location("Somewhere, ME", "Prestige"), ("Somewhere, ME", "ambiguous"))

    def test_a_city_shared_by_the_family_takes_the_name_as_written(self):
        # Noaker's and Noaker's Truck Shop are both in Duncannon, PA; the text
        # says "Noaker's", so that is the shop.
        self.assertEqual(resolve_billing_location("Duncannon, PA", "Noaker's"), ("Noaker's", "name_match"))

    def test_a_family_name_at_an_address_that_is_not_the_familys_stays_ambiguous(self):
        self.assertEqual(resolve_billing_location("Somewhere, PA", "Prestige"), ("Somewhere, PA", "ambiguous"))

    def test_noakers_is_the_default_when_nothing_says_which_of_its_shops(self):
        self.assertEqual(resolve_billing_location(None, "Noaker's"), ("Noaker's", "name_match"))
        self.assertEqual(resolve_billing_location(None, "VIVE COLLISION NOAKERS"), ("Noaker's", "name_match"))
        self.assertEqual(resolve_billing_location("Duncannon, PA", ["VIVE COLLISION OF DUNCANNON"]), ("Noaker's", "city_match"))
        self.assertEqual(resolve_billing_location(None, "Noaker's Truck Shop"), ("Noaker's Truck Shop", "name_match"))

    def test_the_phone_separates_a_shared_city(self):
        # The sheet has no phone for Noaker's Truck Shop; Noaker's has one.
        phone = shop_list.by_name("Noaker's")["phone"]
        self.assertEqual(resolve_billing_location("Duncannon, PA", "Noaker's", phone=phone),
                         ("Noaker's", "name_match"))

    def test_a_printed_location_that_is_the_longer_name(self):
        # "Middletown, NJ" reads the same as the shop name "Middletown - NJ".
        self.assertEqual(resolve_billing_location("Middletown, NJ", "VIVE COLLISION - MIDDLETOWN"),
                         ("Middletown - NJ", "name_match"))

    def test_a_signal_for_another_shop_does_not_settle_the_family(self):
        self.assertEqual(resolve_billing_location(None, "Middletown", phone=shop_list.by_name("Coleman's")["phone"])[1],
                         "ambiguous")


class FuzzyStep(unittest.TestCase):
    def test_a_typo_in_the_shop_name(self):
        self.assertEqual(resolve_billing_location(None, "Colmans Auto Body"), ("Coleman's", "fuzzy_match"))
        self.assertEqual(resolve_billing_location(None, "VIVE COLLISION - CHERRY HIL (W60)"),
                         ("Cherry Hill", "fuzzy_match"))

    def test_an_exact_name_is_not_reported_as_fuzzy(self):
        self.assertEqual(resolve_billing_location(None, "Coleman's Auto Body")[1], "name_match")

    def test_a_short_name_needs_an_exact_match(self):
        for text in ("Acem", "Lnd", "Nk"):
            with self.subTest(text=text):
                self.assertEqual(resolve_billing_location(None, text)[1], "unmapped")

    def test_unrelated_text_is_not_matched(self):
        for text in ("Quirk Auto Group", "Modernization Inc", "Body Shop Supply"):
            with self.subTest(text=text):
                self.assertEqual(resolve_billing_location(None, text)[1], "unmapped")

    def test_a_close_match_wins_over_a_phone_for_another_shop(self):
        self.assertEqual(resolve_billing_location(None, "Colmans Auto Body",
                                                  phone=shop_list.by_name("RP Bell")["phone"]), ("Coleman's", "fuzzy_match"))


class CutOffNames(unittest.TestCase):
    """A name the PDF cut short is the shop it starts."""

    def test_a_cut_off_shop_name(self):
        for text, shop in (("VIVE COLLISION MAINE COLL", "Maine Collision"),
                           ("VIVE COLLISION DBA MAINE COLLI", "Maine Collision"),
                           ("VIVE COLLISION - MAINE", "Maine Collision"),
                           ("VIVE COLLISION-LYNDH", "Lyndhurst")):
            with self.subTest(text=text):
                self.assertEqual(resolve_billing_location(None, [text]), (shop, "fuzzy_match"))

    def test_the_whole_text_being_a_shops_significant_name(self):
        self.assertEqual(resolve_billing_location(None, ["VIVE COLLISION- J.A.S. AUTOBODY"]), ("J.A.S. Auto", "fuzzy_match"))

    def test_a_country_after_the_city_is_not_a_state(self):
        self.assertEqual(resolve_billing_location("Allentown, US", ["VIVE COLLISION"]), ("Lehigh Valley", "city_match"))

    def test_a_city_in_the_shop_text_is_a_city(self):
        self.assertEqual(resolve_billing_location("ESSEX", ["VIVE COLLISION OF SOUTH ORANGE"]), ("Modern", "city_match"))
        self.assertEqual(resolve_billing_location(None, ["VIVE HIGH FALLS"]), ("Jake's", "city_match"))

    def test_a_city_shared_by_shops_in_the_text_is_still_no_match(self):
        self.assertEqual(resolve_billing_location(None, ["VIVE COLLISION OF NEPTUNE"])[1], "unmapped")

    def test_a_street_returned_as_the_location_is_matched_as_a_street(self):
        self.assertEqual(resolve_billing_location("2302 LUCAS TPKE", ["VIVE HIGH FALLS"]), ("Jake's", "street_match"))

    def test_a_generic_word_is_not_a_cut_off_name(self):
        # "Collision" starts "Collision Restoration".
        for text in ("VIVE 508 COLLISION", "CROWN COLLISION", "VIVE COLLISION"):
            self.assertEqual(resolve_billing_location(None, [text])[1], "unmapped")

    def test_a_street_word_is_not_a_cut_off_name(self):
        # "Main" starts "Maine Collision", but "Neptune S Main" is a street.
        self.assertEqual(resolve_billing_location(None, ["VIVE COLLISION -NEPTUNE S MAIN"])[1], "unmapped")


class ShopDetails(unittest.TestCase):
    def test_city_state_and_phone_come_from_the_shop_list(self):
        self.assertEqual(shop_list.shop_details("RP Bell"), {"phone": "(207) 282-6860", "city": "Saco", "state": "ME"})
        self.assertEqual(shop_list.shop_details("coleman's")["city"], "Auburn")

    def test_a_name_that_is_not_a_shop(self):
        self.assertIsNone(shop_list.shop_details("Scarborough"))
        self.assertIsNone(shop_list.shop_details(None))


class ApplyLocation(unittest.TestCase):
    """apply_location() writes the mapped location and the shop's details back
    into vendor_metadata -- the five fields stored with a statement."""

    def test_a_mapped_location_fills_all_five_fields(self):
        meta = apply_location({"shop_or_entity": ["VIVE COLLISION- RP BELL"], "billing_location": "Mechanic Falls, ME"})
        self.assertEqual(
            {k: meta[k] for k in ("billing_location_extracted", "billing_location", "billing_location_source",
                                  "shop_phone", "shop_city", "shop_state")},
            {"billing_location_extracted": "Mechanic Falls, ME", "billing_location": "RP Bell",
             "billing_location_source": "name_match", "shop_phone": "(207) 282-6860",
             "shop_city": "Saco", "shop_state": "ME"})

    def test_customer_phone_and_addresses_are_used(self):
        meta = apply_location({"billing_location": "Mechanic Falls, ME", "customer_phone": "207-282-6860"})
        self.assertEqual((meta["billing_location"], meta["billing_location_source"]), ("RP Bell", "phone_match"))
        meta = apply_location({"billing_location": "Mechanic Falls, ME",
                               "customer_addresses": [{"label": "ship_to", "city": "Auburn", "state": "ME"}]})
        self.assertEqual((meta["billing_location"], meta["shop_city"]), ("Coleman's", "Auburn"))

    def test_an_unmapped_location_keeps_its_value_and_has_no_shop_details(self):
        meta = apply_location({"billing_location": "Scarborough, ME", "shop_or_entity": ["Unknown Body Shop"]})
        self.assertEqual((meta["billing_location_extracted"], meta["billing_location"], meta["billing_location_source"]),
                         ("Scarborough, ME", "Scarborough, ME", "unmapped"))
        self.assertEqual((meta["shop_phone"], meta["shop_city"], meta["shop_state"]), (None, None, None))

    def test_nothing_extracted(self):
        meta = apply_location({})
        self.assertEqual((meta["billing_location_extracted"], meta["billing_location"], meta["billing_location_source"]),
                         (None, None, "unmapped"))

    def test_running_it_twice_keeps_the_extracted_value(self):
        meta = apply_location({"shop_or_entity": ["Coleman's Auto Body"], "billing_location": "Mechanic Falls, ME"})
        apply_location(meta)
        self.assertEqual((meta["billing_location_extracted"], meta["billing_location"]),
                         ("Mechanic Falls, ME", "Coleman's"))

    def test_the_resolver_is_replaceable(self):
        meta = apply_location({"billing_location": "X"}, lambda loc, shop, **kw: ("Y", "printed_new"))
        self.assertEqual((meta["billing_location"], meta["billing_location_source"], meta["shop_city"]),
                         ("Y", "printed_new", None))


class Logging(unittest.TestCase):
    def test_the_extracted_value_is_logged_when_a_mapped_name_replaces_it(self):
        with self.assertLogs("src.validation.location_lookup", level="INFO") as logs:
            resolve_billing_location("Mechanic Falls, ME", "Coleman's Auto Body")
        self.assertIn("'Mechanic Falls, ME'", logs.output[0])
        self.assertIn("name_match", logs.output[0])

    def test_unmapped_and_conflict_are_warnings(self):
        for args in (("Scarborough, ME", None), ("Auburn, ME", None, "(207) 282-6860")):
            with self.subTest(args=args), self.assertLogs("src.validation.location_lookup", level="WARNING"):
                resolve_billing_location(*args)


class Aliases(unittest.TestCase):
    """Names a statement uses that are not the shop's NetSuite name
    (config/location_mapping.json), and the city words NetSuite leaves out."""

    def test_an_alias_names_its_shop_where_the_city_alone_is_shared(self):
        # Bangor, ME holds two shops; Bernatche is the "Bangor" one.
        self.assertEqual(resolve_billing_location("BANGOR ME", ["BERNATCHE AUTO BODY"]), ("Bangor", "name_match"))
        self.assertEqual(resolve_billing_location("BANGOR, ME 04401", ["VIVE COLLISION MAINE COL CTR"]),
                         ("Maine Collision", "name_match"))

    def test_an_alias_outranks_a_city_that_points_elsewhere(self):
        # Auburn, ME is Coleman's; the name says Hewitt's, whose name also holds Caron's.
        self.assertEqual(resolve_billing_location("AUBURN, ME", ["CARONS BODY SHOP DBA HEWITTS AUTO B"]),
                         ("Hewitt's", "name_match"))
        self.assertEqual(resolve_billing_location("Auburn, ME", ["SEBAGO LAKE COLLISION, LLC"]), ("Sebago", "name_match"))
        self.assertEqual(resolve_billing_location("MANCHESTER, NH", ["VIVE COLLISION- CROSSROADS NH"]),
                         ("Crossroads", "name_match"))

    def test_an_alias_does_not_outrank_a_street_at_another_shop(self):
        street = [{"street": "181 S Main St", "city": "Neptune", "state": "NJ"}]
        self.assertEqual(resolve_billing_location("Neptune, NJ", ["M3 Collision"], addresses=street),
                         ("Neptune, NJ", "conflict"))

    def test_abbreviated_shop_names(self):
        self.assertEqual(resolve_billing_location("MT LAUREL TWP NJ", ["VIVE COLLISION - MT LAUREL (C60)"]),
                         ("Mount Laurel", "name_match"))
        self.assertEqual(resolve_billing_location("HUDSON, MA", ["VIVE BODY & PAINT COLLISION"]),
                         ("Body & Paint Center", "name_match"))
        self.assertEqual(resolve_billing_location("Lyndon, Vermont", ["VIVE - N E K Collision Repair"]),
                         ("NEK", "name_match"))

    def test_a_township_suffix_is_not_part_of_the_city(self):
        for location in ("MT LAUREL TWP NJ", "Mount Laurel Township, New Jersey", "Mount Laurel, NJ"):
            with self.subTest(location=location):
                self.assertEqual(resolve_billing_location(location, None), ("Mount Laurel", "city_match"))

    def test_aliases_are_told_from_shop_names(self):
        self.assertTrue(shop_list.is_alias("bernatche"))
        self.assertFalse(shop_list.is_alias("bangor"))


if __name__ == "__main__":
    unittest.main()
