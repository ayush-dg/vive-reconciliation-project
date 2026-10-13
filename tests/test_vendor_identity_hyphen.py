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


if __name__ == "__main__":
    unittest.main()
