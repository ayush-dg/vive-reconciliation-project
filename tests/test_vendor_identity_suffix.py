"""
tests/test_vendor_identity_suffix.py

resolve_vendor_id() ignores company-type suffixes (Inc, LLC, Co, Corp, ...),
added 2026-10-08 after a scanned Keystone statement read "Keystone
Automotive Industries, Inc." and got an unmapped fallback vendor_id
(prod STMT-E1BFC5BC, "No lines read").
"""

import json
import os
import sys
import unittest
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.vendor_identity import CONFIG_PATH, _normalize, resolve_vendor_id


class TestCompanySuffixes(unittest.TestCase):

    def test_suffix_variants_resolve(self):
        for name in ("Keystone Automotive Industries, Inc.", "KEYSTONE AUTOMOTIVE INDUSTRIES INC",
                     "Keystone Automotive Industries LLC", "Keystone Automotive Industries"):
            with self.subTest(name=name):
                self.assertEqual(resolve_vendor_id(name), "KEYSTONE_AUTOMOTIVE_INDUSTRIES")

    def test_a_name_made_only_of_suffixes_is_kept(self):
        self.assertEqual(_normalize("Inc."), "INC")
        self.assertIsNone(resolve_vendor_id("Inc"))

    def test_no_two_vendors_collide_once_suffixes_are_dropped(self):
        with open(CONFIG_PATH) as f:
            aliases = json.load(f)
        owners = defaultdict(set)
        for vendor_id, names in aliases.items():
            for name in names:
                owners[_normalize(name)].add(vendor_id)
        self.assertEqual({k: v for k, v in owners.items() if len(v) > 1}, {})


if __name__ == "__main__":
    unittest.main()
