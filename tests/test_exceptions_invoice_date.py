"""
tests/test_exceptions_invoice_date.py

The statement line's invoice date on the Exceptions review page (2026-11-12,
UAT 22): silver.recon_exceptions has no date, so the list's muted date line
and the detail panel's "Invoice date" box showed "—". web/queries.py's
get_exception_kinds_and_dates() now takes it from the recon table's
line_date for the exception's lines, else Silver's line_date (the same lines,
then statement_id + invoice_number, then original_invoice_number), sharing
the page's one recon query and one Silver query with the Bill/Credit label.

The recon table is an in-memory SQLite built by the real migrations; Silver
is a stubbed recon_query (and, once, a temporary SQLite with the same
column names, to run the real SQL). Nothing touches the network.
"""

import os
import re
import sqlite3
import sys
import unittest
from datetime import date, datetime
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse import recon_table as rt
from tests.test_exceptions_bill_credit import SILVER_COLUMNS, _Calls, _client, _unknown_columns
from tests.test_recon_table import _DbTest
from web import queries
from web.routers import exceptions

STMT = {"statement_id": "STMT-DT", "vendor_id": "TEST_VENDOR", "vendor_name": "Test Vendor",
        "statement_period": "2026-10"}


def _exc(eid, inv, reason="Not Found in NetSuite", amount=10.0, **extra):
    row = {"exception_id": eid, "statement_id": "STMT-DT", "invoice_number": inv, "vendor_id": "TEST_VENDOR",
           "exception_reason": reason, "statement_amount": amount, "erp_amount": None,
           "match_confidence": None, "date_raised": None, "days_open": None, "invoice_date": None,
           "original_invoice_number": None}
    row.update(extra)
    return row


# E-RECON: date on its recon row.        E-LINE: no recon date, Silver line via its statement_line_id.
# E-INV: no recon row, Silver by invoice_number.   E-ORIG: Silver by original_invoice_number only.
# E-NONE: nothing anywhere.   E-HAS: already has a date (kept).   E-MANY: two lines, two dates (earliest).
EXCS = [
    _exc("E-RECON", "INV-2001"),
    _exc("E-LINE", "INV-2002"),
    _exc("E-INV", "INV-2003"),
    _exc("E-ORIG", "2004", original_invoice_number="INV-2004"),
    _exc("E-NONE", "INV-2005"),
    _exc("E-HAS", "INV-2006", invoice_date="2026-09-30"),
    _exc("E-MANY", "INV-2007"),
]
LINES = [
    {"statement_line_id": "D1", "line_number": 1, "invoice_number": "INV-2001", "charge_amount": 10.0,
     "line_date": "2026-10-01"},
    {"statement_line_id": "D2", "line_number": 2, "invoice_number": "INV-2002", "charge_amount": 10.0},
    {"statement_line_id": "D7", "line_number": 7, "invoice_number": "INV-2007", "charge_amount": 5.0,
     "line_date": "2026-10-09"},
    {"statement_line_id": "D8", "line_number": 8, "invoice_number": "INV-2007", "charge_amount": 5.0,
     "line_date": "2026-10-04"},
]
RESULTS = {
    "D1": {"status": "Not found in NetSuite", "exception_id": "E-RECON", "statement_amount": 10.0},
    "D2": {"status": "Not found in NetSuite", "exception_id": "E-LINE", "statement_amount": 10.0},
    "D7": {"status": "Not found in NetSuite", "exception_id": "E-MANY", "statement_amount": 5.0},
    "D8": {"status": "Not found in NetSuite", "exception_id": "E-MANY", "statement_amount": 5.0},
}


def _sl(line_id, inv, line_date, original=None, line_type="CHARGE"):
    return {"statement_line_id": line_id, "statement_id": "STMT-DT", "line_type": line_type, "line_date": line_date,
            "invoice_number": inv, "original_invoice_number": original or inv, "line_type_trusted": 1}


# Silver returns date objects (Fabric `date` column).
SILVER = [
    _sl("D1", "INV-2001", date(2026, 9, 1)),            # recon's own date wins over this
    _sl("D2", "INV-2002", date(2026, 10, 2)),
    _sl("D3", "INV-2003", date(2026, 10, 3)),
    _sl("D4", "4", date(2026, 10, 4), original="INV-2004"),
    _sl("D5", "INV-2005", None),
    _sl("D6", "INV-2006", date(2026, 10, 6)),
    _sl("D7", "INV-2007", date(2026, 10, 9)),
    _sl("D8", "INV-2007", date(2026, 10, 4)),
]
EXPECTED = {"E-RECON": "2026-10-01", "E-LINE": "2026-10-02", "E-INV": "2026-10-03", "E-ORIG": "2026-10-04",
            "E-MANY": "2026-10-04"}


class DateRuleTests(unittest.TestCase):
    INDEX = queries._silver_date_index(SILVER)

    def _date(self, exc, links=()):
        return queries.exception_invoice_date(exc, list(links), self.INDEX)

    def test_recon_line_date_first(self):
        self.assertEqual(self._date(EXCS[0], [{"statement_line_id": "D1", "line_date": "2026-10-01"}]), "2026-10-01")

    def test_silver_line_of_the_linked_line(self):
        self.assertEqual(self._date(EXCS[1], [{"statement_line_id": "D2", "line_date": None}]), "2026-10-02")

    def test_silver_by_invoice_number_then_original(self):
        self.assertEqual(self._date(EXCS[2]), "2026-10-03")
        self.assertEqual(self._date(EXCS[3]), "2026-10-04")

    def test_no_date_anywhere(self):
        self.assertIsNone(self._date(EXCS[4]))
        self.assertIsNone(self._date(_exc("E-X", None)))
        self.assertIsNone(self._date(_exc("E-OTHER", "INV-2001", statement_id="STMT-OTHER")))  # statement-scoped

    def test_the_earliest_of_several(self):
        links = [{"statement_line_id": "D7", "line_date": "2026-10-09"}, {"statement_line_id": "D8", "line_date": "2026-10-04"}]
        self.assertEqual(self._date(EXCS[6], links), "2026-10-04")
        self.assertEqual(self._date(EXCS[6]), "2026-10-04")  # Silver by invoice number too

    def test_date_forms(self):
        self.assertEqual(queries._iso_date(date(2026, 1, 2)), "2026-01-02")
        self.assertEqual(queries._iso_date(datetime(2026, 1, 2, 13, 5)), "2026-01-02")
        self.assertEqual(queries._iso_date("2026-01-02T00:00:00"), "2026-01-02")
        for bad in (None, "", "01/02/2026", "n/a", 20260102, "2026-13-01"):
            self.assertIsNone(queries._iso_date(bad), bad)


class LookupTests(_DbTest):
    def setUp(self):
        super().setUp()
        rt.replace_auto_rows("STMT-DT", rt.build_auto_rows(STMT, LINES, RESULTS))
        self.recon = _Calls(lambda sql, params: [dict(r) for r in self.conn.execute(sql, params or []).fetchall()])
        self.silver = _Calls(lambda sql, params: [dict(r) for r in SILVER])
        for name, fn in (("execute_query", self.recon), ("recon_query", self.silver)):
            patcher = mock.patch.object(queries, name, fn)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_every_source_on_one_page(self):
        _, dates = queries.get_exception_kinds_and_dates([dict(e) for e in EXCS])
        self.assertEqual(dates, EXPECTED)

    def test_an_existing_date_is_not_overwritten(self):
        _, dates = queries.get_exception_kinds_and_dates([dict(e) for e in EXCS])
        self.assertNotIn("E-HAS", dates)

    def test_one_recon_and_one_silver_query_for_the_page(self):
        many = [dict(e, exception_id=f"{e['exception_id']}-{i}") for i in range(10) for e in EXCS]
        queries.get_exception_kinds_and_dates(many)
        self.assertEqual((len(self.recon.sql), len(self.silver.sql)), (1, 1))
        self.assertIn("line_date", self.recon.sql[0])

    def test_failed_lookups_give_no_dates(self):
        with mock.patch.object(queries, "recon_query", side_effect=RuntimeError("down")):
            _, dates = queries.get_exception_kinds_and_dates([dict(e) for e in EXCS])
        self.assertEqual(dates, {"E-RECON": "2026-10-01", "E-MANY": "2026-10-04"})  # the recon dates only
        with mock.patch.object(queries, "execute_query", side_effect=RuntimeError("down")), \
                mock.patch.object(queries, "recon_query", side_effect=RuntimeError("down")):
            self.assertEqual(queries.get_exception_kinds_and_dates([dict(e) for e in EXCS]), ({}, {}))


class SilverSqlTests(unittest.TestCase):
    def _sql(self):
        seen = []
        with mock.patch.object(queries, "recon_query", lambda sql, params=None: seen.append((sql, params)) or []):
            queries._silver_lines(["STMT-DT"])
        return seen[0]

    def test_columns_exist_in_the_dbt_models(self):
        sql, _ = self._sql()
        for column in ("sl.line_date", "sl.invoice_number", "sl.original_invoice_number", "st.statement_id"):
            self.assertIn(column, sql)
        self.assertTrue({"line_date", "invoice_number", "original_invoice_number"} <= SILVER_COLUMNS["statement_line"])
        self.assertEqual(_unknown_columns(sql), [])
        # The checker would catch a wrong name (the sl.vendor_id lesson).
        self.assertEqual(_unknown_columns(sql.replace("sl.line_date", "sl.invoice_date")), ["sl.invoice_date"])

    def test_the_real_sql_runs_on_sqlite(self):
        sql, params = self._sql()
        conn = sqlite3.connect(":memory:")
        conn.execute("ATTACH ':memory:' AS silver")
        conn.execute("CREATE TABLE silver.statement_line (statement_line_id, statement_id, line_type, line_date,"
                     " invoice_number, original_invoice_number)")
        conn.execute("CREATE TABLE silver.statement (statement_id, vendor_id)")
        conn.execute("CREATE TABLE silver.vendor_line_selection_rule (vendor_id, is_active, rule_type, credit_indicator)")
        conn.executemany("INSERT INTO silver.statement_line VALUES (?, ?, ?, ?, ?, ?)",
                         [("A", "STMT-DT", "CHARGE", "2026-10-01", "INV-1", "INV-1"),
                          ("B", "STMT-DT", "CREDIT", "2026-10-02", "CM-2", "CM-2"),
                          ("C", "STMT-OTHER", "CHARGE", "2026-10-03", "INV-3", "INV-3")])
        conn.execute("INSERT INTO silver.statement VALUES ('STMT-DT', 'TEST_VENDOR')")
        rows = conn.execute(sql, params).fetchall()
        self.assertEqual(sorted((r[0], r[3], r[6]) for r in rows), [("A", "2026-10-01", 1), ("B", "2026-10-02", 1)])
        conn.execute("INSERT INTO silver.vendor_line_selection_rule VALUES ('TEST_VENDOR', 1, 'transaction_code_priority', NULL)")
        self.assertEqual({r[6] for r in conn.execute(sql, params).fetchall()}, {0})


def _page(selected="E-RECON", recon=None, silver=None):
    """The review page with the real lookup on stubbed recon/Silver data;
    returns (html, recon calls, silver calls)."""
    recon = recon or _Calls(lambda sql, params: [])
    silver = silver or _Calls(lambda sql, params: [dict(r) for r in SILVER])
    patches = [
        mock.patch.object(queries, "execute_query", recon),
        mock.patch.object(queries, "recon_query", silver),
        mock.patch.object(exceptions.queries, "get_statement_by_id", return_value=dict(STMT)),
        mock.patch.object(exceptions.queries, "get_open_exceptions", side_effect=lambda *a: [dict(e) for e in EXCS]),
        mock.patch.object(exceptions.queries, "get_exception_counts", return_value=(9, 2)),
        mock.patch.object(exceptions.queries, "get_statement_shop", return_value=None),
        mock.patch.object(exceptions.queries, "get_manual_matches", return_value=[]),
        mock.patch.object(exceptions.queries, "get_cleared_exceptions", return_value=[]),
        mock.patch.object(exceptions, "fetch_netsuite_record_for_invoice", return_value=None),
        mock.patch.object(exceptions, "_writeback_status", return_value=None),
        mock.patch.object(exceptions, "_statement_pdf_url", return_value=None),
        mock.patch.object(exceptions, "sidebar_context", return_value={}),
        mock.patch.object(exceptions.completion, "history", return_value=[]),
        mock.patch.object(exceptions.completion, "current_status", return_value=None),
    ]
    for p in patches:
        p.start()
    try:
        resp = _client().get(f"/exceptions/Test%20Vendor?statement_id=STMT-DT&selected={selected}")
    finally:
        for p in reversed(patches):
            p.stop()
    assert resp.status_code == 200
    return resp.text, recon, silver


def _recon_rows():
    return [{"exception_id": "E-RECON", "statement_line_id": "D1", "netsuite_record_type": None, "line_date": "2026-10-01"},
            {"exception_id": "E-LINE", "statement_line_id": "D2", "netsuite_record_type": None, "line_date": None}]


def _row_dates(html):
    rows = re.findall(r'class="exception-row[^"]*">(.*?)</a>', html, re.S)
    return [re.search(r'<div class="edate">(.*?)</div>', r, re.S).group(1) for r in rows]


def _detail_date(html):
    return re.search(r'<div class="fb-label">Invoice date</div><div class="fb-value">(.*?)</div>', html).group(1)


class PageTests(unittest.TestCase):
    def test_the_list_rows_show_the_dates(self):
        html, _, _ = _page(recon=_Calls(lambda sql, params: _recon_rows()))
        self.assertEqual(_row_dates(html), ["01 Oct 2026", "02 Oct 2026", "03 Oct 2026", "04 Oct 2026", "—",
                                            "30 Sep 2026", "04 Oct 2026"])

    def test_the_detail_box_shows_it(self):
        recon = lambda: _Calls(lambda sql, params: _recon_rows())
        self.assertEqual(_detail_date(_page("E-RECON", recon=recon())[0]), "01 Oct 2026")
        self.assertEqual(_detail_date(_page("E-INV", recon=recon())[0]), "03 Oct 2026")
        self.assertEqual(_detail_date(_page("E-NONE", recon=recon())[0]), "—")
        self.assertEqual(_detail_date(_page("E-HAS", recon=recon())[0]), "30 Sep 2026")

    def test_one_recon_and_one_silver_query_per_page(self):
        _, recon, silver = _page(recon=_Calls(lambda sql, params: _recon_rows()))
        self.assertEqual((len(recon.sql), len(silver.sql)), (1, 1))

    def test_a_failed_lookup_leaves_the_page_as_before(self):
        down = _Calls(lambda sql, params: (_ for _ in ()).throw(RuntimeError("down")))
        html, _, _ = _page(recon=down, silver=_Calls(lambda sql, params: (_ for _ in ()).throw(RuntimeError("down"))))
        self.assertEqual(_row_dates(html), ["—", "—", "—", "—", "—", "30 Sep 2026", "—"])
        self.assertEqual(_detail_date(html), "—")

    def test_only_the_date_lines_change(self):
        with_dates, _, _ = _page(recon=_Calls(lambda sql, params: _recon_rows()))
        undated_recon = [dict(r, line_date=None) for r in _recon_rows()]
        undated_silver = [dict(r, line_date=None) for r in SILVER]
        without, _, _ = _page(recon=_Calls(lambda sql, params: undated_recon),
                              silver=_Calls(lambda sql, params: undated_silver))
        strip = lambda h: re.sub(r'(<div class="edate">|<div class="fb-label">Invoice date</div><div class="fb-value">)'
                                 r'[^<]*</div>', r"\1</div>", h)
        self.assertNotEqual(with_dates, without)
        self.assertEqual(strip(with_dates), strip(without))


if __name__ == "__main__":
    unittest.main()
