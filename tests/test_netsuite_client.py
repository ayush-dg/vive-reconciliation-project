"""
tests/test_netsuite_client.py

Offline tests for the sandbox guard and domain/realm derivation in
src/netsuite/client.py. No NetSuite calls are made.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.netsuite.client import (
    NetSuiteClient,
    NetSuiteConfigError,
    derive_account_forms,
)

_FULL_ENV = {
    "SANDBOX_ACCOUNT_ID": "7321761-sb1",
    "SANDBOX_CONSUMER_KEY": "ck",
    "SANDBOX_CONSUMER_SECRET": "cs",
    "SANDBOX_TOKEN_ID": "ti",
    "SANDBOX_TOKEN_SECRET": "ts",
}


class DeriveAccountFormsTests(unittest.TestCase):
    def test_hyphen_lowercase_input(self):
        self.assertEqual(derive_account_forms("7321761-sb1"), ("7321761-sb1", "7321761_SB1"))

    def test_underscore_uppercase_input_gives_same_result(self):
        self.assertEqual(derive_account_forms("7321761_SB1"), ("7321761-sb1", "7321761_SB1"))

    def test_surrounding_whitespace_is_ignored(self):
        self.assertEqual(derive_account_forms(" 7321761-SB2 "), ("7321761-sb2", "7321761_SB2"))

    def test_production_id_is_refused(self):
        with self.assertRaises(NetSuiteConfigError):
            derive_account_forms("7321761")

    def test_ambiguous_ids_are_refused(self):
        for bad in ("", None, "sb1", "7321761-sb", "7321761-rp1", "7321761-sb1-extra"):
            with self.subTest(bad=bad), self.assertRaises(NetSuiteConfigError):
                derive_account_forms(bad)


class ClientConstructionTests(unittest.TestCase):
    def test_domain_and_realm_come_from_the_same_value(self):
        with mock.patch.dict(os.environ, _FULL_ENV, clear=True):
            client = NetSuiteClient(session=mock.Mock())
        self.assertEqual(
            client.base_url,
            "https://7321761-sb1.suitetalk.api.netsuite.com/services/rest",
        )
        self.assertEqual(client.realm, "7321761_SB1")

    def test_missing_credential_is_refused(self):
        env = {k: v for k, v in _FULL_ENV.items() if k != "SANDBOX_TOKEN_SECRET"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(NetSuiteConfigError):
                NetSuiteClient(session=mock.Mock())

    def test_production_account_id_is_refused_at_construction(self):
        env = dict(_FULL_ENV, SANDBOX_ACCOUNT_ID="7321761")
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(NetSuiteConfigError):
                NetSuiteClient(session=mock.Mock())


if __name__ == "__main__":
    unittest.main()
