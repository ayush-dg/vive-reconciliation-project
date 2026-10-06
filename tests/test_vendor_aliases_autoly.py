"""
tests/test_vendor_aliases_autoly.py

config/vendor_aliases.json entries for the Autoly vendors (2026-10-06):
extract_autoly reports the printed letterhead name, and every name variant
seen for the same vendor (letterhead, or what the AI path called it) must
resolve to the one vendor_id with the most history.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.vendor_identity import resolve_vendor_id


class TestAutolyVendorAliases(unittest.TestCase):

    def assert_one_id(self, vendor_id, *names):
        for name in names:
            self.assertEqual(resolve_vendor_id(name), vendor_id, name)

    def test_goyettes(self):
        self.assert_one_id("GOYETTE'S_INC", "GOYETTE'S INC PRP-NE", "Goyette's Inc", "GOYETTE'S INC")

    def test_dings(self):
        self.assert_one_id("DING'S_AUTO_PARTS", "Ding's Auto Parts", "Ding's Auto Parts - Autoly CT05")

    def test_bow(self):
        self.assert_one_id("BOW_AUTO_PARTS_-_AUTOLY", "Bow Auto Parts - AUTOLY", "Bow Auto Parts")

    def test_chucks(self):
        # The Noakers scan's letterhead is Chuck's Douglassville; the AI read
        # the logo ("Chuck's Auto Parts Solutions").
        self.assert_one_id("CHUCK'S_DOUGLASSVILLE_-_AUTOLY", "Chuck's Douglassville - AUTOLY", "Chuck's Auto Parts Solutions")

    def test_other_vendors_are_unaffected(self):
        self.assertEqual(resolve_vendor_id("Fenix NE"), "FENIX_NE")
        self.assertIsNone(resolve_vendor_id("Brown's Auto Salvage- Autoly"))
        self.assertIsNone(resolve_vendor_id("Gear Six Auto Parts"))
        self.assertIsNone(resolve_vendor_id("Goyette Chevrolet"))
        self.assertIsNone(resolve_vendor_id("Ding's Collision"))


if __name__ == "__main__":
    unittest.main()
