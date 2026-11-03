"""
tests/test_netsuite_record_link.py

The "Find in NetSuite" panel's bill numbers open the record in NetSuite
(2026-11-03): web/deps.py netsuite_record_url() and its use in
_netsuite_search_results.html. Nothing here touches NetSuite.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web.deps import netsuite_record_url, templates

PROD = {"NETSUITE_CONNECT_ACCOUNT_ID": "7321761", "NETSUITE_ACCOUNT_ID": ""}
BASE = "https://7321761.app.netsuite.com/app/accounting/transactions/"


def _row(**overrides):
    row = {"record_type": "Bill", "is_credit": False, "tranid": "824029", "internal_id": "4603276", "vendor_name": "V",
           "entity_id": "1", "total": 12.5, "trandate": "9/1/2026", "trandate_display": "Sep 1, 2026",
           "duedate": None, "duedate_display": "", "status_label": "Open", "ro_number": None,
           "location_code": "64", "location_name": "Lamon", "transaction_number": "VENDBILL1"}
    row.update(overrides)
    return row


def _render(row):
    return templates.get_template("_netsuite_search_results.html").render(
        result={"rows": [row], "row_count": 1, "truncated": False, "error": False, "needs_filter": False,
                "message": None}, last_sync=None)


class RecordUrlTests(unittest.TestCase):
    def test_a_bill_opens_its_vendbill_page(self):
        with mock.patch.dict(os.environ, PROD):
            self.assertEqual(netsuite_record_url("Bill", "4603276"), BASE + "vendbill.nl?id=4603276")

    def test_a_credit_opens_its_vendcred_page(self):
        with mock.patch.dict(os.environ, PROD):
            self.assertEqual(netsuite_record_url("credit", 555), BASE + "vendcred.nl?id=555")

    def test_the_account_falls_back_to_netsuite_account_id(self):
        with mock.patch.dict(os.environ, {"NETSUITE_CONNECT_ACCOUNT_ID": "", "NETSUITE_ACCOUNT_ID": "7321761"}):
            self.assertEqual(netsuite_record_url("Bill", "1"), BASE + "vendbill.nl?id=1")

    def test_a_sandbox_account_uses_netsuites_domain_form(self):
        with mock.patch.dict(os.environ, {"NETSUITE_CONNECT_ACCOUNT_ID": "7321761_SB1"}):
            self.assertEqual(netsuite_record_url("Bill", "9"),
                             "https://7321761-sb1.app.netsuite.com/app/accounting/transactions/vendbill.nl?id=9")

    def test_anything_unusable_gives_no_link(self):
        with mock.patch.dict(os.environ, PROD):
            for record_type, internal_id in (("Bill", None), ("Bill", ""), ("Bill", "12a"), ("Bill", "1;x"),
                                             ("Invoice", "1"), (None, "1")):
                with self.subTest(record_type=record_type, internal_id=internal_id):
                    self.assertIsNone(netsuite_record_url(record_type, internal_id))
        with mock.patch.dict(os.environ, {"NETSUITE_CONNECT_ACCOUNT_ID": "", "NETSUITE_ACCOUNT_ID": ""}):
            self.assertIsNone(netsuite_record_url("Bill", "1"))
        with mock.patch.dict(os.environ, {"NETSUITE_CONNECT_ACCOUNT_ID": "evil.example/x"}):
            self.assertIsNone(netsuite_record_url("Bill", "1"))


class SearchPanelLinkTests(unittest.TestCase):
    def test_the_bill_number_links_to_netsuite_in_a_new_tab(self):
        with mock.patch.dict(os.environ, PROD):
            html = _render(_row())
        self.assertIn(f'href="{BASE}vendbill.nl?id=4603276" target="_blank" rel="noopener noreferrer"', html)
        self.assertIn(">824029<", html)
        self.assertIn('class="ns-pick"', html)   # picking for "Accept as match" is unchanged

    def test_a_credit_links_to_its_credit_page(self):
        with mock.patch.dict(os.environ, PROD):
            html = _render(_row(record_type="Credit", is_credit=True, tranid="CM23", internal_id="555"))
        self.assertIn(f'href="{BASE}vendcred.nl?id=555"', html)

    def test_without_an_internal_id_or_account_the_number_stays_plain(self):
        with mock.patch.dict(os.environ, PROD):
            html = _render(_row(internal_id=None))
        self.assertNotIn("app.netsuite.com", html)
        self.assertIn('<span class="ns-bill-no">824029</span>', html)
        with mock.patch.dict(os.environ, {"NETSUITE_CONNECT_ACCOUNT_ID": "", "NETSUITE_ACCOUNT_ID": ""}):
            self.assertNotIn("app.netsuite.com", _render(_row()))


if __name__ == "__main__":
    unittest.main()
