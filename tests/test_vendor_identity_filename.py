"""
tests/test_vendor_identity_filename.py

resolve_vendor_id_from_filename() (added 2026-10-30): when a statement prints
no vendor name, intake derives one from the file name -- "Mr.Tire_CherryHill_0926.pdf"
-> "Mr.Tire Cherryhill 0926" -- which no alias matches as a whole, so prod got
vendor_id MR.TIRE_CHERRYHILL_0926 (a new, unmapped id every month). For those
names only, a name that starts with a known alias resolves to that vendor.
Reads the real config/vendor_aliases.json.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.vendor_identity import resolve_vendor_id, resolve_vendor_id_from_filename


def _from_file(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "intake_for_test", os.path.join(os.path.dirname(__file__), "..", "notebooks", "01_document_intake.py"))
    intake = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(intake)
    return intake.derive_vendor_name_from_filename(name)


class TestFilenameDerivedNames(unittest.TestCase):

    def test_mr_tire_file_names_resolve_whatever_the_month(self):
        self.assertEqual(resolve_vendor_id_from_filename("Mr.Tire Cherryhill 0926"), "MR_TIRE")
        self.assertEqual(resolve_vendor_id_from_filename("Mr.Tire Cherryhill 1026"), "MR_TIRE")
        self.assertEqual(resolve_vendor_id_from_filename("Mr Tire Lyndhurst 1126"), "MR_TIRE")

    def test_the_longest_matching_alias_wins(self):
        # "Mr. Tire Auto Centers" and "Mr. Tire" both start this name.
        self.assertEqual(resolve_vendor_id_from_filename("Mr Tire Auto Centers Cherry Hill 0926"), "MR_TIRE")

    def test_whole_name_matches_are_unchanged(self):
        self.assertEqual(resolve_vendor_id_from_filename("Goodwin's Chevrolet-Mazda"), "GOODWINS")

    def test_no_alias_at_the_start_is_still_none(self):
        self.assertIsNone(resolve_vendor_id_from_filename("Unknown Vendor May2026"))
        self.assertIsNone(resolve_vendor_id_from_filename("Cherryhill Mr Tire 0926"))  # alias not at the start
        self.assertIsNone(resolve_vendor_id_from_filename(None))

    def test_a_partial_first_word_does_not_count(self):
        # "CAP" is an alias; "Capital Auto" must not become CONTINENTAL_AUTO_PARTS.
        self.assertIsNone(resolve_vendor_id_from_filename("Capital Auto 0926"))

    def test_printed_names_do_not_use_the_prefix_match(self):
        # Short aliases like CAP/VIP must not swallow a printed vendor name.
        self.assertIsNone(resolve_vendor_id("VIP Collision Supply"))
        self.assertIsNone(resolve_vendor_id("Mr.Tire Cherryhill 0926"))

    def test_the_real_file_name(self):
        name = _from_file("Mr.Tire_CherryHill_0926.pdf")
        self.assertEqual(name, "Mr.Tire Cherryhill 0926")
        self.assertEqual(resolve_vendor_id_from_filename(name), "MR_TIRE")


if __name__ == "__main__":
    unittest.main()
