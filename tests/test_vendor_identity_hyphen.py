"""
tests/test_vendor_identity_hyphen.py

resolve_vendor_id() also tries the name with hyphens and slashes read as
word breaks (added 2026-10-13): prod's "Goodwin's Chevrolet-Mazda" statement
got an unmapped fallback vendor_id because the hyphen glued two words
together. The plain form is still tried first and every alias is registered
under both forms, so nothing that resolved before resolves differently.
Reads the real config/vendor_aliases.json.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.vendor_identity import CONFIG_PATH, resolve_vendor_id


class TestHyphensAndSlashes(unittest.TestCase):

    def test_hyphenated_name_resolves(self):
        self.assertEqual(resolve_vendor_id("Goodwin's Chevrolet-Mazda"), "GOODWINS")

    def test_names_that_matched_before_still_match(self):
        self.assertEqual(resolve_vendor_id("Goodwins Chevrolet Mazda"), "GOODWINS")
        self.assertEqual(resolve_vendor_id("1-800-RADIATOR"), "1800_RADIATOR")
        self.assertEqual(resolve_vendor_id("1800 Radiator"), "1800_RADIATOR")

    def test_every_alias_still_resolves_to_its_own_vendor(self):
        with open(CONFIG_PATH) as f:
            aliases = json.load(f)
        wrong = [(name, vendor_id, resolve_vendor_id(name))
                 for vendor_id, names in aliases.items() for name in names
                 if resolve_vendor_id(name) != vendor_id]
        self.assertEqual(wrong, [])

    def test_thompson_volkswagen(self):
        for name in ("Thompson Volkswagen, Inc.", "THOMPSON VOLKSWAGEN INC", "Thompson VW"):
            with self.subTest(name=name):
                self.assertEqual(resolve_vendor_id(name), "THOMPSON_VOLKSWAGEN")

    def test_unknown_name_still_unresolved(self):
        self.assertIsNone(resolve_vendor_id("Some-New Vendor / Shop"))



class TestNameFallbacks(unittest.TestCase):
    """Fallback forms (2026-10-13), tried only after the plain ones miss --
    the vendor names below are exactly what prod extracted."""

    def test_company_suffix_dropped(self):
        self.assertEqual(resolve_vendor_id("Lia Group Payables LLC"), "LIA_AUTO_GROUP")

    def test_bracketed_text_dropped(self):
        self.assertEqual(resolve_vendor_id("nucar (The Reynolds and Reynolds Company)"), "NUCAR")

    def test_text_after_dash_dropped(self):
        self.assertEqual(resolve_vendor_id("Techzone - NOTE OUR NEW ADDRESS"), "TECHZONE_AIRBAG_SERVICE")

    def test_lia_stores(self):
        for name in ("Lia Hyundai of Hartford", "Lia Hyundai", "LIA VOLKSWAGEN", "LIA HONDA OF ENFIELD"):
            with self.subTest(name=name):
                self.assertEqual(resolve_vendor_id(name), "LIA_AUTO_GROUP")

    def test_vendors_set_up_2026_10_13(self):
        for name, vendor_id in (("SCHALLER HONDA / SUBARU", "SCHALLER_SUBARU"), ("Columbia Ford", "COLUMBIA_FORD"),
                                ("EZ AUTO GLASS INSTALLERS, INC", "EZ_AUTO_GLASS_INSTALLERS"),
                                ("Mercedes-Benz of Boston", "MERCEDES_BENZ_OF_BOSTON"),
                                ("WEBER BROTHERS AUTO, INC", "WEBER_BROTHERS_AUTO")):
            with self.subTest(name=name):
                self.assertEqual(resolve_vendor_id(name), vendor_id)

    def test_vendors_set_up_2026_10_14(self):
        for name, vendor_id in (("Cherry Hill Triplex", "CHERRY_HILL_TRIPLEX"), ("L & M AUTO CENTER", "L_&_M_AUTO_CENTER"),
                                ("Bennetts Auto Recovery", "BENNETTS_AUTO_RECOVERY"),
                                ("Bennett's Auto Recovery", "BENNETTS_AUTO_RECOVERY")):
            with self.subTest(name=name):
                self.assertEqual(resolve_vendor_id(name), vendor_id)

    def test_vendors_not_set_up_stay_unresolved(self):
        # Asbury was the example here until it was set up on 2026-10-19
        # (see tests/test_asbury_setup.py); any name with no alias entry works.
        for name in ("Acme Imaginary Auto Parts",):
            with self.subTest(name=name):
                self.assertIsNone(resolve_vendor_id(name))

if __name__ == "__main__":
    unittest.main()
