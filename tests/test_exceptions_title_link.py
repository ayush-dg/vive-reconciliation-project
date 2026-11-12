"""
tests/test_exceptions_title_link.py

The Exceptions review detail title links to NetSuite (2026-11-12): when the
page has loaded a record into the "NetSuite record" panel (Amount Mismatch,
Appears to be Paid), web/routers/exceptions.py's _netsuite_record_link()
builds that record's URL with web.deps.netsuite_record_url() and the <h2>
wraps "Invoice #..." in a link to it. No record, or no usable id -> plain
title. The "(Bill)/(Credit)" label stays outside the link.

Every query is stubbed; nothing touches the network.
"""

import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.test_exceptions_bill_credit import EXCS, EXPECTED, STMT, _client
from web.routers import exceptions

ACCOUNT = {"NETSUITE_CONNECT_ACCOUNT_ID": "1234567_SB1", "NETSUITE_ACCOUNT_ID": ""}
NO_ACCOUNT = {"NETSUITE_CONNECT_ACCOUNT_ID": "", "NETSUITE_ACCOUNT_ID": ""}
BASE = "https://1234567-sb1.app.netsuite.com/app/accounting/transactions/"
BILL_RECORD = {"id": 4711, "tranid": "CM-1005", "total": 16.0, "status": "A", "_source_table": "netsuite_vendorbill"}
CREDIT_RECORD = {"id": "4712", "tranid": "CM-1005", "total": 16.0, "status": "A",
                 "_source_table": "netsuite_vendorcredit"}
LINK = re.compile(r'<a class="einv-ns-link"[^>]*>.*?</a>', re.S)


def _page(selected, record, env=ACCOUNT, rows=EXCS):
    """The review page with `selected` open and fetch_netsuite_record_for_invoice
    returning `record`; returns (html, the fetch mock, the payments mock)."""
    url = f"/exceptions/Test%20Vendor?statement_id=STMT-BC&selected={selected}"
    fetch = mock.Mock(side_effect=lambda *a: None if record is None else dict(record))
    payments = mock.Mock(return_value=[])
    patches = [
        mock.patch.dict(os.environ, env),
        mock.patch.object(exceptions.queries, "get_statement_by_id", return_value=dict(STMT)),
        mock.patch.object(exceptions.queries, "get_open_exceptions", side_effect=lambda *a: [dict(e) for e in rows]),
        mock.patch.object(exceptions.queries, "get_exception_counts", return_value=(9, 3)),
        mock.patch.object(exceptions.queries, "get_statement_shop", return_value=None),
        mock.patch.object(exceptions.queries, "get_manual_matches", return_value=[]),
        mock.patch.object(exceptions.queries, "get_cleared_exceptions", return_value=[]),
        mock.patch.object(exceptions.queries, "get_exception_kinds_and_dates", return_value=(dict(EXPECTED), {})),
        mock.patch.object(exceptions, "fetch_netsuite_record_for_invoice", fetch),
        mock.patch.object(exceptions, "fetch_bill_payments", payments),
        mock.patch.object(exceptions, "_writeback_status", return_value=None),
        mock.patch.object(exceptions, "_statement_pdf_url", return_value=None),
        mock.patch.object(exceptions, "sidebar_context", return_value={}),
        mock.patch.object(exceptions.completion, "history", return_value=[]),
        mock.patch.object(exceptions.completion, "current_status", return_value=None),
    ]
    for p in patches:
        p.start()
    try:
        resp = _client().get(url)
    finally:
        for p in reversed(patches):
            p.stop()
    assert resp.status_code == 200
    return resp.text, fetch, payments


def _title(html):
    return re.search(r"<h2>(.*?)</h2>", html, re.S).group(1)


def _strip_link(html):
    """The page with the title link taken out, leaving its text."""
    return re.sub(r'<a class="einv-ns-link"[^>]*>(.*?)<span class="ns-ext" aria-hidden="true">↗</span></a>',
                  r"\1", html, flags=re.S)


class NetsuiteRecordLinkTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ACCOUNT)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_bill_and_credit(self):
        self.assertEqual(exceptions._netsuite_record_link(BILL_RECORD), BASE + "vendbill.nl?id=4711")
        self.assertEqual(exceptions._netsuite_record_link(CREDIT_RECORD), BASE + "vendcred.nl?id=4712")

    def test_no_link_without_a_usable_record(self):
        for record in (None, {}, dict(BILL_RECORD, id=None), dict(BILL_RECORD, id="12a"),
                       dict(BILL_RECORD, id="4711 OR 1=1"), dict(BILL_RECORD, _source_table="netsuite_journal"),
                       {"id": 4711}):
            self.assertIsNone(exceptions._netsuite_record_link(record), record)

    def test_no_link_without_an_account(self):
        with mock.patch.dict(os.environ, NO_ACCOUNT):
            self.assertIsNone(exceptions._netsuite_record_link(BILL_RECORD))


class TitleLinkPageTests(unittest.TestCase):
    def test_amount_mismatch_bill_links_the_invoice_number(self):
        html, fetch, _ = _page("E-NSCR", BILL_RECORD)
        self.assertEqual(
            _title(html),
            f'<a class="einv-ns-link" href="{BASE}vendbill.nl?id=4711" target="_blank" rel="noopener noreferrer"\n'
            '          title="Open bill CM-1005 in NetSuite">Invoice #CM-1005'
            '<span class="ns-ext" aria-hidden="true">↗</span></a> <span class="einv-kind einv-kind-credit">(Credit)</span>')
        fetch.assert_called_once_with("TEST_VENDOR", "Test Vendor", "CM-1005")

    def test_credit_record_links_the_credit_page(self):
        html, _, _ = _page("E-NSCR", CREDIT_RECORD)
        link = LINK.search(_title(html)).group(0)
        self.assertIn(f'href="{BASE}vendcred.nl?id=4712"', link)
        self.assertIn('title="Open credit CM-1005 in NetSuite"', link)
        self.assertNotIn("einv-kind", link)

    def test_appears_to_be_paid_links_too(self):
        html, fetch, payments = _page("E-PAID", dict(BILL_RECORD, id=4713, tranid="INV-1004"))
        self.assertIn(f'href="{BASE}vendbill.nl?id=4713"', _title(html))
        self.assertIn('title="Open bill INV-1004 in NetSuite"', _title(html))
        fetch.assert_called_once()
        payments.assert_called_once_with(4713)

    def test_not_found_has_no_link_and_no_lookup(self):
        html, fetch, _ = _page("E-MISS", BILL_RECORD)
        self.assertEqual(_title(html), 'Invoice #INV-1001 <span class="einv-kind einv-kind-bill">(Bill)</span>')
        fetch.assert_not_called()

    def test_no_record_or_bad_id_is_plain_text(self):
        for record in (None, dict(BILL_RECORD, id=None), dict(BILL_RECORD, id="abc"), {k: v for k, v in
                       BILL_RECORD.items() if k != "id"}):
            html, _, _ = _page("E-NSCR", record)
            self.assertEqual(_title(html), 'Invoice #CM-1005 <span class="einv-kind einv-kind-credit">(Credit)</span>', record)
            self.assertNotIn("einv-ns-link", html)

    def test_no_account_is_plain_text(self):
        html, _, _ = _page("E-NSCR", BILL_RECORD, env=NO_ACCOUNT)
        self.assertNotIn("einv-ns-link", html)

    def test_everything_is_escaped(self):
        rows = [dict(e, invoice_number='<i>"x"&</i>') if e["exception_id"] == "E-NSCR" else e for e in EXCS]
        html, _, _ = _page("E-NSCR", BILL_RECORD, rows=rows)
        title = _title(html)
        self.assertIn('title="Open bill &lt;i&gt;&#34;x&#34;&amp;&lt;/i&gt; in NetSuite"', title)
        self.assertIn("Invoice #&lt;i&gt;&#34;x&#34;&amp;&lt;/i&gt;<span", title)
        self.assertNotIn("<i>", html)

    def test_only_the_title_changes(self):
        with_link, _, _ = _page("E-NSCR", BILL_RECORD)
        without, _, _ = _page("E-NSCR", BILL_RECORD, env=NO_ACCOUNT)
        self.assertEqual(with_link.count('class="einv-ns-link"'), 1)
        self.assertNotEqual(with_link, without)
        self.assertEqual(_strip_link(with_link), without)

    def test_the_record_is_fetched_once(self):
        _, fetch, _ = _page("E-NSCR", BILL_RECORD)
        self.assertEqual(fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
