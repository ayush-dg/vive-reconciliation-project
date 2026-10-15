"""
tests/test_silver_compile_cache_key.py

The direct Silver build caches its compiled SQL under a fingerprint. The
SQL names the environment's Lakehouse/Warehouse, so the fingerprint must
differ between dev and prod -- otherwise a machine that ran against dev
reuses dev's compile against prod (2026-10-15: "Invalid object name
'if_vive_lakehouse.bronze.raw_statement'" on prod).
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse import silver_build


class TestCompileCacheKey(unittest.TestCase):

    def _fp(self, **env):
        base = {"FABRIC_LAKEHOUSE_NAME": "lh", "FABRIC_WAREHOUSE_NAME": "wh", "FABRIC_SQL_ENDPOINT": "ep"}
        with mock.patch.dict(os.environ, {**base, **env}):
            return silver_build._project_fingerprint()

    def test_same_environment_same_key(self):
        self.assertEqual(self._fp(), self._fp())

    def test_each_environment_setting_changes_the_key(self):
        for var, value in (("FABRIC_LAKEHOUSE_NAME", "if_vive_lakehouse_prod"),
                           ("FABRIC_WAREHOUSE_NAME", "other_wh"), ("FABRIC_SQL_ENDPOINT", "other_ep")):
            with self.subTest(var=var):
                self.assertNotEqual(self._fp(), self._fp(**{var: value}))


if __name__ == "__main__":
    unittest.main()
