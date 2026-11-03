"""
tests/test_vendor_name_prefixes.py

Vendor families known by their first word (config/vendor_name_prefixes.json,
2026-11-03): every LKQ location resolves to LKQ, so its statements use LKQ's
field mapping and NetSuite vendors instead of failing "No lines read" under a
new id (prod: LKQ Slippery Rock 2026-11-02, LKQ Buffalo 2026-11-03).
Reads the real config files.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.vendor_identity import resolve_vendor_id, resolve_vendor_id_from_filename


class LkqLocationTests(unittest.TestCase):
    def test_any_lkq_location_is_lkq(self):
        for name in ("LKQ Buffalo", "LKQ Slippery Rock", "LKQ-Buffalo", "lkq buffalo", "LKQ", "LKQ Corp of Rochester"):
            with self.subTest(name=name):
                self.assertEqual(resolve_vendor_id(name), "LKQ")

    def test_listed_aliases_still_win(self):
        self.assertEqual(resolve_vendor_id("LKQ Gorham Auto"), "LKQ")
        self.assertEqual(resolve_vendor_id("Goodwin's Chevrolet-Mazda"), "GOODWINS")

    def test_only_a_whole_first_word_counts(self):
        for name in ("LKQX Parts", "Royal Used LKQ Parts", "Buffalo LKQ", "Bulkq Supply"):
            with self.subTest(name=name):
                self.assertIsNone(resolve_vendor_id(name))

    def test_other_vendors_are_unchanged(self):
        self.assertIsNone(resolve_vendor_id("Unknown Vendor May2026"))
        self.assertIsNone(resolve_vendor_id("Mr.Tire Cherryhill 0926"))  # file-name prefixes stay file-name only
        self.assertIsNone(resolve_vendor_id(None))

    def test_file_name_derived_names_too(self):
        self.assertEqual(resolve_vendor_id_from_filename("Lkq Buffalo 1026"), "LKQ")


if __name__ == "__main__":
    unittest.main()
