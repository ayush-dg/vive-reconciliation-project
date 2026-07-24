"""
tests/test_shop_owners.py

Tests for src/shop_owners.py's vendor_id -> shop owner lookup (see
config/shop_owners.json, migrations/009_add_routing_aging.sql).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import shop_owners


class TestGetShopOwner(unittest.TestCase):

    def setUp(self):
        # Reset the module-level cache so each test starts fresh and
        # test_missing_config_file_returns_none_for_everything (below)
        # can safely repoint CONFIG_PATH without leaking into other tests.
        shop_owners._cache = None
        self._real_config_path = shop_owners.CONFIG_PATH

    def tearDown(self):
        shop_owners.CONFIG_PATH = self._real_config_path
        shop_owners._cache = None

    def test_known_vendor_id_returns_name_and_email(self):
        self.assertEqual(shop_owners.get_shop_owner("KSI_TRADING_CORP."), "Shop Manager <shop@vive.com>")
        self.assertEqual(shop_owners.get_shop_owner("ASTECH"), "asTech Owner <astech@vive.com>")

    def test_unknown_vendor_id_returns_none(self):
        self.assertIsNone(shop_owners.get_shop_owner("SOME_OTHER_VENDOR"))

    def test_falsy_vendor_id_returns_none(self):
        self.assertIsNone(shop_owners.get_shop_owner(None))
        self.assertIsNone(shop_owners.get_shop_owner(""))

    def test_missing_config_file_returns_none_for_everything(self):
        shop_owners.CONFIG_PATH = "does/not/exist.json"
        shop_owners._cache = None

        self.assertIsNone(shop_owners.get_shop_owner("KSI_TRADING_CORP."))


if __name__ == "__main__":
    unittest.main()
