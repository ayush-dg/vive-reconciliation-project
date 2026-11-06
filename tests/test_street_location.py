"""
tests/test_street_location.py

Street-address matching, aliases and the NetSuite-sourced shop list
(src/validation/street_match.py, location_lookup.py, shop_list.py).

The shops are a small synthetic copy of config/netsuite_locations.json's
format -- name, street, city, state, zip, phone -- using real shop addresses,
so nothing here depends on a live NetSuite sync. The cases come from the
'location testing' statements (Lexus of Edison, Cherry Hill Triplex, Bertera,
Sullivan Tire, ...).
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.validation import shop_list
from src.validation.location_lookup import resolve_billing_location
from src.validation.street_match import parse_street, same_street

LOCATIONS = {
    "1": {"name": "Clarkstown", "street": "95 NY-304", "city": "Nanuet", "state": "NY", "phone": "(845) 627-3100"},
    "2": {"name": "Corporate", "street": "", "city": "", "state": "", "phone": ""},
    "3": {"name": "Coleman's", "street": "1524 Minot Avenue", "city": "Auburn", "state": "ME", "phone": "(207) 784-6121"},
    "4": {"name": "Hewitt's", "street": "345 East Elm Street", "city": "Yarmouth", "state": "ME", "phone": "(207) 846-3113"},
    "5": {"name": "RP Bell", "street": "7 Ocean Park Road", "city": "Saco", "state": "ME", "phone": "(207) 282-6860"},
    "10": {"name": "Middletown", "street": "950 Aquidneck Avenue", "city": "Middletown", "state": "RI", "phone": "(401) 847-0664"},
    "19": {"name": "Middletown - NJ", "street": "660 Route 35", "city": "Middletown", "state": "NJ", "phone": "(732) 671-1331"},
    "28": {"name": "Highway 35", "street": "508 State Route 35 North", "city": "Neptune", "state": "NJ", "phone": "(732) 988-9401"},
    "29": {"name": "South Main", "street": "181 South Main St", "city": "Neptune", "state": "NJ", "phone": "(732) 774-6635"},
    "32": {"name": "Noaker's", "street": "819 New Bloomfield Rd", "city": "Duncannon", "state": "PA", "phone": "(717) 834-6500"},
    "53": {"name": "Maurice & Son", "street": "232 A College Ave", "city": "Waterville", "state": "ME", "phone": "(207) 453-6533"},
    "64": {"name": "Lamon", "street": "1 Main St", "city": "Mt Holly", "state": "NJ", "phone": "(609) 267-7073"},
    "83": {"name": "West Hartford", "street": "1072 New Britain Ave", "city": "West Hartford", "state": "CT", "phone": "(860) 236-5020"},
    "88": {"name": "zz_Growth", "street": "1 Growth Way", "city": "Auburn", "state": "ME", "phone": ""},
    "89": {"name": "Noaker's Truck Shop", "street": "819 New Bloomfield Rd", "city": "Duncannon", "state": "PA", "phone": ""},
}
MAPPING = {
    "excluded": ["zz_Growth"],
    "aliases": {
        "Highway 35": ["M3 Collision", "M 3 Collision", "M3 Collision Center", "HW 3"],
        "South Main": ["M3 South Main", "M3 181"],
        "West Hartford": ["WH"],
        "No Such Shop": ["Ghost Alias"],
    },
}


def write_json(directory, name, data):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


class NetSuiteShops(unittest.TestCase):
    """Runs every test against the synthetic NetSuite location list."""

    def setUp(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(self._cleanup, directory)
        self.addCleanup(shop_list.reload)  # registered first, so it runs after the patches are undone
        patches = (mock.patch.object(shop_list, "NETSUITE_LOCATIONS_PATH", write_json(directory, "ns.json", LOCATIONS)),
                   mock.patch.object(shop_list, "MAPPING_PATH", write_json(directory, "mapping.json", MAPPING)))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        shop_list.reload()

    @staticmethod
    def _cleanup(directory):
        for name in os.listdir(directory):
            os.remove(os.path.join(directory, name))
        os.rmdir(directory)


class StreetLines(unittest.TestCase):
    def test_the_same_address_written_two_ways(self):
        for a, b in (("508 HIGHWAY 35", "508 State Route 35 North"),
                     ("508 STATE ROUTE 35 N", "508 State Route 35 North"),
                     ("660 Hwy 35", "660 Route 35"),
                     ("181 S Main St", "181 South Main St"),
                     ("181 Main St", "181 South Main St"),
                     ("1072 N BRITAIN AVE", "1072 New Britain Ave"),
                     ("232 College Ave", "232 A College Ave"),
                     ("95 NY-304", "95 NY-304")):
            with self.subTest(a=a, b=b):
                self.assertTrue(same_street(a, b))

    def test_different_addresses(self):
        for a, b in (("509 Highway 35", "508 State Route 35 North"),   # house number
                     ("508 Highway 9", "508 State Route 35 North"),    # route number
                     ("181 Elm St", "181 South Main St"),              # street name
                     ("Main St", "181 South Main St"),                 # no house number
                     ("", "181 South Main St")):
            with self.subTest(a=a, b=b):
                self.assertFalse(same_street(a, b))

    def test_parts(self):
        self.assertEqual(parse_street("508 STATE ROUTE 35 N"), ("508", "35", ["35"]))
        self.assertEqual(parse_street("181 S Main St"), ("181", "", ["main"]))
        self.assertEqual(parse_street(None), ("", "", []))


class StreetStep(NetSuiteShops):
    def test_the_street_line_alone_finds_the_shop(self):
        # Lexus of Edison (M3 Hwy35): the shop is just "VIVE COLLISION".
        addresses = [{"label": "bill_to", "street": "508 STATE ROUTE 35 N", "city": "Neptune", "state": "NJ"}]
        self.assertEqual(resolve_billing_location("Neptune, NJ", ["VIVE COLLISION"], addresses=addresses),
                         ("Highway 35", "street_match"))

    def test_south_main_by_its_street(self):
        addresses = [{"label": "bill_to", "street": "181 S MAIN ST", "city": "Neptune", "state": "NJ"}]
        self.assertEqual(resolve_billing_location("Neptune, NJ", ["VIVE COLLISION"], addresses=addresses),
                         ("South Main", "street_match"))

    def test_n_britain_ave_is_new_britain_ave(self):
        addresses = [{"label": "bill_to", "street": "1072 N BRITAIN AVE", "city": "W HARTFORD", "state": "CT"}]
        self.assertEqual(resolve_billing_location("W Hartford, CT", ["VIVE COLLISION - XYZ"], addresses=addresses),
                         ("West Hartford", "street_match"))

    def test_a_street_in_another_town_is_not_the_same_place(self):
        addresses = [{"label": "bill_to", "street": "181 SOUTH MAIN ST", "city": "Springfield", "state": "MA"}]
        # Springfield, MA has no shop in this list, and the street is South Main's in Neptune, NJ.
        self.assertEqual(resolve_billing_location("Springfield, MA", ["VIVE COLLISION"], addresses=addresses),
                         ("Springfield, MA", "unmapped"))

    def test_two_shops_at_one_address_take_the_default(self):
        addresses = [{"label": "bill_to", "street": "819 New Bloomfield Rd", "city": "Duncannon", "state": "PA"}]
        self.assertEqual(resolve_billing_location("Duncannon, PA", ["VIVE COLLISION"], addresses=addresses),
                         ("Noaker's", "street_match"))

    def test_noakers_at_the_shared_address_is_noakers(self):
        # KSI (Noakers): "Noakers Collision" at 819 New Bloomfield Rd, which is both shops' address.
        addresses = [{"label": "bill_to", "street": "819 New Bloomfield Rd", "city": "Duncannon", "state": "PA"}]
        self.assertEqual(resolve_billing_location("Duncannon, PA", ["VIVE COLLISION - Noakers Collision"],
                                                  addresses=addresses), ("Noaker's", "name_match"))
        self.assertEqual(resolve_billing_location("Duncannon, PA", ["Noaker's Truck Shop"], addresses=addresses),
                         ("Noaker's Truck Shop", "name_match"))

    def test_an_address_with_no_street_is_skipped(self):
        addresses = [{"label": "bill_to", "street": "", "city": "Neptune", "state": "NJ"}]
        self.assertEqual(resolve_billing_location("Neptune, NJ", ["VIVE COLLISION"], addresses=addresses),
                         ("Neptune, NJ", "unmapped"))

    def test_the_name_wins_over_a_street_at_another_shop(self):
        addresses = [{"label": "bill_to", "street": "1524 Minot Ave", "city": "Auburn", "state": "ME"}]
        self.assertEqual(resolve_billing_location("Auburn, ME", ["VIVE COLLISION - RP BELL"], addresses=addresses),
                         ("RP Bell", "name_match"))

    def test_name_and_street_agreeing(self):
        addresses = [{"label": "bill_to", "street": "508 HIGHWAY 35", "city": "NEPTUNE", "state": "NJ"}]
        self.assertEqual(resolve_billing_location("NEPTUNE, NJ", ["VIVE COLLISION - M3 COLLISION (HW 3"], addresses=addresses),
                         ("Highway 35", "name_match"))


class Aliases(NetSuiteShops):
    def test_m3_names(self):
        for text, shop in (("M 3 Collision", "Highway 35"), ("M3 Collision Center", "Highway 35"),
                           ("VIVE COLLISION - M3 COLLISION (HW 3", "Highway 35"),
                           ("VIVE COLLISION - M3 181", "South Main"), ("M3 SOUTH MAIN COLLISION CENTER", "South Main")):
            with self.subTest(text=text):
                self.assertEqual(resolve_billing_location(None, [text]), (shop, "name_match"))

    def test_wh_is_west_hartford(self):
        self.assertEqual(resolve_billing_location("W Hartford, CT", ["VIVE COLLISION - WH"]),
                         ("West Hartford", "name_match"))

    def test_an_alias_for_a_shop_that_is_not_in_the_list_is_ignored(self):
        self.assertEqual(resolve_billing_location(None, ["Ghost Alias"])[1], "unmapped")

    def test_excluded_locations_are_not_shops(self):
        self.assertNotIn("zz_Growth", shop_list.names())
        self.assertEqual(resolve_billing_location(None, ["zz_Growth"])[1], "unmapped")


class Normalization(NetSuiteShops):
    def test_and_is_ampersand(self):
        self.assertEqual(resolve_billing_location(None, ["Vive Collision Maurice and Son"]),
                         ("Maurice & Son", "name_match"))
        self.assertEqual(resolve_billing_location(None, ["MAURICE & SON"]), ("Maurice & Son", "name_match"))

    def test_abbreviated_place_words(self):
        self.assertEqual(resolve_billing_location("W Hartford, CT", None), ("West Hartford", "city_match"))
        self.assertEqual(resolve_billing_location("MOUNT HOLLY, NJ", None), ("Lamon", "city_match"))
        self.assertEqual(resolve_billing_location("Mt Holly, NJ", None), ("Lamon", "city_match"))

    def test_a_zip_after_the_state_is_ignored(self):
        self.assertEqual(resolve_billing_location("NATICK, MA 01760", None)[1], "unmapped")  # no Natick in this list
        self.assertEqual(resolve_billing_location("Auburn, ME 04210-8802", None), ("Coleman's", "city_match"))
        self.assertEqual(resolve_billing_location("MOUNT HOLLY, NJ 08060", None), ("Lamon", "city_match"))
        self.assertEqual(resolve_billing_location("Auburn ME 04210", None), ("Coleman's", "city_match"))

    def test_a_city_with_no_state_maps_when_one_shop_is_in_it(self):
        self.assertEqual(resolve_billing_location("AUBURN", None), ("Coleman's", "city_match"))
        self.assertEqual(resolve_billing_location("Saco", None), ("RP Bell", "city_match"))

    def test_a_city_with_no_state_does_not_guess_between_shops(self):
        # Middletown is in RI and NJ; Neptune has two shops.
        self.assertEqual(resolve_billing_location("MIDDLETOWN", None), ("MIDDLETOWN", "ambiguous"))
        self.assertEqual(resolve_billing_location("Neptune", None), ("Neptune", "unmapped"))

    def test_text_that_is_no_city_stays_unmapped(self):
        self.assertEqual(resolve_billing_location("2302 LUCAS TPKE", None), ("2302 LUCAS TPKE", "unmapped"))

    def test_a_state_written_out(self):
        self.assertEqual(resolve_billing_location("Auburn, Maine", None), ("Coleman's", "city_match"))
        self.assertEqual(resolve_billing_location("scarborough, Maine", ["Hewitt's Auto Body"]),
                         ("Hewitt's", "name_match"))


class WithoutAddressesInTheList(unittest.TestCase):
    """While config/netsuite_locations.json has no addresses (not yet synced
    with them) the shop list sheet is used."""

    def setUp(self):
        directory = tempfile.mkdtemp()
        path = write_json(directory, "ns.json", {"5": {"name": "RP Bell", "inactive": False}})
        patch = mock.patch.object(shop_list, "NETSUITE_LOCATIONS_PATH", path)
        self.addCleanup(shop_list.reload)  # registered first, so it runs after the patch is undone
        patch.start()
        shop_list.reload()
        self.addCleanup(patch.stop)
        self.addCleanup(os.rmdir, directory)
        self.addCleanup(os.remove, path)

    def test_the_sheet_is_the_fallback(self):
        self.assertEqual(shop_list.by_phone("(207) 282-6860")["name"], "RP Bell")
        self.assertEqual(resolve_billing_location(None, ["VIVE COLLISION- RP BELL"]), ("RP Bell", "name_match"))


if __name__ == "__main__":
    unittest.main()
