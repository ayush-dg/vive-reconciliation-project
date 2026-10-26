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


_PROD_ENV = {
    "PROD_ACCOUNT_ID": "7321761",
    "PROD_CONSUMER_KEY": "pck",
    "PROD_CONSUMER_SECRET": "pcs",
    "PROD_TOKEN_ID": "pti",
    "PROD_TOKEN_SECRET": "pts",
}
_BOTH = dict(_FULL_ENV, **_PROD_ENV)


def _client(env, session=None):
    with mock.patch.dict(os.environ, env, clear=True):
        return NetSuiteClient(session=session or mock.Mock())


class EnvironmentSwitchTests(unittest.TestCase):
    """NETSUITE_ACCOUNT_ID alone decides sandbox or production."""

    def test_a_sandbox_id_selects_the_sandbox_and_its_credentials(self):
        client = _client(dict(_BOTH, NETSUITE_ACCOUNT_ID="7321761-sb1"))
        self.assertEqual(client.environment.name, "sandbox")
        self.assertFalse(client.environment.is_production)
        self.assertEqual(client.base_url, "https://7321761-sb1.suitetalk.api.netsuite.com/services/rest")
        self.assertEqual(client.realm, "7321761_SB1")
        self.assertEqual(client._auth.client.client_key, "ck")
        self.assertEqual(client.environment.exception_list_table, "customlist_exception")

    def test_a_plain_id_selects_production_and_its_credentials(self):
        client = _client(dict(_BOTH, NETSUITE_ACCOUNT_ID="7321761"))
        self.assertTrue(client.environment.is_production)
        self.assertEqual(client.base_url, "https://7321761.suitetalk.api.netsuite.com/services/rest")
        self.assertEqual(client.realm, "7321761")
        self.assertEqual(client._auth.client.client_key, "pck")
        self.assertEqual(client._auth.client.resource_owner_key, "pti")
        self.assertEqual(client.environment.exception_list_table, "customlist673")
        self.assertEqual(client.environment.label, "PRODUCTION 7321761")

    def test_either_sandbox_spelling_works(self):
        for raw in ("7321761-sb1", "7321761_SB1", ' "7321761-SB1" '):
            with self.subTest(raw=raw):
                env = dict(_BOTH, NETSUITE_ACCOUNT_ID=raw, SANDBOX_ACCOUNT_ID="7321761_SB1")
                self.assertEqual(_client(env).domain_id, "7321761-sb1")

    def test_with_nothing_selected_it_is_the_sandbox(self):
        client = _client(_BOTH)          # NETSUITE_ACCOUNT_ID not set
        self.assertEqual(client.environment.name, "sandbox")
        self.assertEqual(client._auth.client.client_key, "ck")

    def test_nothing_configured_at_all_is_refused(self):
        with self.assertRaises(NetSuiteConfigError):
            _client({})

    def test_ambiguous_account_ids_are_refused(self):
        for bad in ("sb1", "7321761-sb", "7321761-rp1", "7321761-sb1-extra", "acme", "7321761 1", "7321761-"):
            with self.subTest(bad=bad), self.assertRaises(NetSuiteConfigError):
                _client(dict(_BOTH, NETSUITE_ACCOUNT_ID=bad))

    def test_production_without_its_own_credentials_is_refused(self):
        with self.assertRaises(NetSuiteConfigError) as ctx:
            _client(dict(_FULL_ENV, NETSUITE_ACCOUNT_ID="7321761"))   # only the sandbox keys exist
        self.assertIn("PROD_", str(ctx.exception))

    def test_a_credential_set_must_belong_to_the_account_selected(self):
        cases = [
            dict(_BOTH, NETSUITE_ACCOUNT_ID="7321761", PROD_ACCOUNT_ID="7321761-sb1"),   # sandbox id in the prod slot
            dict(_BOTH, NETSUITE_ACCOUNT_ID="7321761", PROD_ACCOUNT_ID="9999999"),       # another account
            dict(_BOTH, NETSUITE_ACCOUNT_ID="7321761-sb1", SANDBOX_ACCOUNT_ID="7321761"),  # prod id in the sandbox slot
            dict(_BOTH, NETSUITE_ACCOUNT_ID="7321761-sb1", SANDBOX_ACCOUNT_ID="7321761-sb2"),
        ]
        for env in cases:
            with self.subTest(env=(env["NETSUITE_ACCOUNT_ID"], env["PROD_ACCOUNT_ID"], env["SANDBOX_ACCOUNT_ID"])):
                with self.assertRaises(NetSuiteConfigError):
                    _client(env)


class ProductionWritesNeedArmingTests(unittest.TestCase):
    def _session(self):
        session = mock.Mock()
        session.request.return_value = mock.Mock(ok=True, status_code=204,
                                                 headers={"Location": "https://x/customrecord_statement_line/9"})
        session.request.return_value.json.return_value = {"items": []}
        return session

    def test_production_reads_work_without_the_flag(self):
        session = self._session()
        client = _client(dict(_BOTH, NETSUITE_ACCOUNT_ID="7321761"), session)
        self.assertEqual(client.suiteql("SELECT 1"), [])
        session.request.assert_called_once()

    def test_production_writes_are_blocked_without_the_flag_and_nothing_is_sent(self):
        from src.netsuite.guard import WriteBlocked
        session = self._session()
        client = _client(dict(_BOTH, NETSUITE_ACCOUNT_ID="7321761"), session)
        with mock.patch.dict(os.environ, dict(_BOTH, NETSUITE_ACCOUNT_ID="7321761"), clear=True):
            with self.assertRaises(WriteBlocked):
                client.patch_record("vendorbill", "500", {"custbody_reconciled": True})
            with self.assertRaises(WriteBlocked):
                client.create_record("customrecord_statement_line", {
                    "name": "n", "custrecord_sl_statement_id": "STMT-1", "custrecord_sl_invoice_number": "I"})
            with self.assertRaises(WriteBlocked):
                client.delete_record("customrecord_statement_line", "9", "STMT-1")
        session.request.assert_not_called()

    def test_any_value_other_than_true_leaves_production_locked(self):
        from src.netsuite.guard import WriteBlocked
        for value in ("", "false", "1", "yes", "TRUEISH"):
            with self.subTest(value=value):
                session = self._session()
                env = dict(_BOTH, NETSUITE_ACCOUNT_ID="7321761", NETSUITE_PROD_WRITES_ENABLED=value)
                client = _client(env, session)
                with mock.patch.dict(os.environ, env, clear=True), self.assertRaises(WriteBlocked):
                    client.patch_record("vendorbill", "500", {"custbody_reconciled": True})
                session.request.assert_not_called()

    def test_the_flag_arms_production_but_the_allowlist_still_applies(self):
        from src.netsuite.guard import WriteBlocked
        session = self._session()
        env = dict(_BOTH, NETSUITE_ACCOUNT_ID="7321761", NETSUITE_PROD_WRITES_ENABLED="true")
        client = _client(env, session)
        with mock.patch.dict(os.environ, env, clear=True):
            client.patch_record("vendorbill", "500", {"custbody_reconciled": True})
            self.assertEqual(session.request.call_count, 1)
            with self.assertRaises(WriteBlocked):
                client.patch_record("vendorbill", "500", {"memo": "no"})
            self.assertEqual(session.request.call_count, 1)

    def test_the_sandbox_never_needs_the_flag(self):
        session = self._session()
        env = dict(_BOTH, NETSUITE_ACCOUNT_ID="7321761-sb1")
        client = _client(env, session)
        with mock.patch.dict(os.environ, env, clear=True):
            client.patch_record("vendorbill", "500", {"custbody_reconciled": True})
        session.request.assert_called_once()

    def test_the_exception_list_table_follows_the_environment(self):
        from src.netsuite import writeback as wb

        class Ns:
            def __init__(self, environment):
                self.environment, self.queries = environment, []

            def suiteql(self, query):
                self.queries.append(query)
                return [{"id": "1", "name": "Amount differs"}]

        for account, table in (("7321761-sb1", "customlist_exception"), ("7321761", "customlist673")):
            with self.subTest(account=account):
                ns = Ns(_client(dict(_BOTH, NETSUITE_ACCOUNT_ID=account)).environment)
                self.assertEqual(wb.fetch_exception_list_ids(ns), {"Amount differs": "1"})
                self.assertIn(f"FROM {table}", ns.queries[0])


if __name__ == "__main__":
    unittest.main()
