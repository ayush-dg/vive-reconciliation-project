"""
tests/test_netsuite_search_live.py

"Find in NetSuite" on live NetSuite (SuiteAnalytics Connect, 2026-10-27):
the query built for each filter (shapes confirmed live against production --
bill status must be spelled 'VendBill:A', a credit's open amount is its main
line's foreignpaymentamountunused, dates go through TO_DATE), the
NETSUITE_SEARCH_SOURCE switch with its Fabric fallback, and the "Already
matched" mark from the recon table. Nothing here touches NetSuite or Fabric.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matching import netsuite_search as ns
from web import queries
from web.deps import templates


class BuildConnectSelectTests(unittest.TestCase):
    def build(self, table=ns.BILL_TABLE, **kw):
        return ns.build_connect_select(table, **kw)

    def test_bill_open_and_paid_use_the_full_status_codes(self):
        sql, params = self.build(statuses={"open"})
        self.assertIn("t.status = ?", sql)
        self.assertIn("VendBill:A", params)
        _, params = self.build(statuses={"paid"})
        self.assertIn("VendBill:B", params)
        sql, _ = self.build(statuses={"open", "paid"})
        self.assertNotIn("t.status", sql.split("WHERE")[1])

    def test_credit_open_and_paid_use_the_main_lines_unused_amount(self):
        sql, params = self.build(ns.CREDIT_TABLE, statuses={"open"})
        self.assertIn("tl.foreignpaymentamountunused > 0", sql)
        self.assertEqual(params[0], "VendCred")
        sql, _ = self.build(ns.CREDIT_TABLE, statuses={"paid"})
        self.assertIn("tl.foreignpaymentamountunused IS NULL OR tl.foreignpaymentamountunused <= 0", sql)

    def test_vendor_shop_amount_invoice_and_dates_are_bound_parameters(self):
        sql, params = self.build(entity_ids=["81232", "46932"], locations=["64"], bounds=(1272.31, 1272.33),
                                 invoice_contains="  25%_off ", date_from="2026-09-01", date_to="2026-09-30",
                                 statuses={"open", "paid"})
        self.assertIn("t.entity IN (?,?)", sql)
        self.assertIn("tl.location IN (?)", sql)
        self.assertIn("ABS(t.foreigntotal) BETWEEN ? AND ?", sql)
        self.assertIn("LOWER(t.tranid) LIKE LOWER(?) ESCAPE '\\'", sql)
        self.assertIn("t.trandate >= TO_DATE(?, 'YYYY-MM-DD')", sql)
        self.assertIn("t.trandate <= TO_DATE(?, 'YYYY-MM-DD')", sql)
        self.assertEqual(params, ["VendBill", 81232, 46932, 64, 1272.31, 1272.33, "%25\\%\\_off%",
                                  "2026-09-01", "2026-09-30"])

    def test_vendor_ids_that_are_not_numbers_match_nothing_rather_than_everything(self):
        sql, params = self.build(entity_ids=["1 OR 1=1"])
        self.assertIn("1 = 0", sql)
        self.assertNotIn("1 OR 1=1", sql + str(params))

    def test_at_least_and_sort_and_limit(self):
        sql, params = self.build(bounds=(100.0, None), sort_amount=-250.5, limit=25)
        self.assertIn("ABS(t.foreigntotal) >= ?", sql)
        self.assertIn(100.0, params)
        self.assertIn("ORDER BY ABS(ABS(t.foreigntotal) - 250.50) ASC", sql)
        self.assertTrue(sql.startswith("SELECT TOP 25 "))
        self.assertIn("ORDER BY t.trandate DESC", self.build()[0])

    def test_rows_carry_the_shop_from_the_main_line_and_the_vendor_name(self):
        sql, _ = self.build()
        self.assertIn("LEFT JOIN transactionline tl ON tl.transaction = t.id AND tl.mainline = 'T'", sql)
        self.assertIn("LEFT JOIN vendor v ON v.id = t.entity", sql)


class SourceSwitchTests(unittest.TestCase):
    def test_search_source_follows_its_own_setting_then_the_matching_switch(self):
        with mock.patch.dict(os.environ, {"NETSUITE_SEARCH_SOURCE": "connect", "NETSUITE_SOURCE": "fabric"}):
            self.assertEqual(ns.search_source(), "connect")
        with mock.patch.dict(os.environ, {"NETSUITE_SEARCH_SOURCE": "", "NETSUITE_SOURCE": "connect"}):
            self.assertEqual(ns.search_source(), "connect")
        with mock.patch.dict(os.environ, {"NETSUITE_SEARCH_SOURCE": "", "NETSUITE_SOURCE": ""}):
            self.assertEqual(ns.search_source(), "fabric")

    def _search(self, live, fabric=lambda *a: []):
        with mock.patch.dict(os.environ, {"NETSUITE_SEARCH_SOURCE": "connect"}), \
                mock.patch.object(ns, "_run_search_connect", side_effect=live), \
                mock.patch.object(ns, "_run_search", side_effect=fabric), \
                mock.patch.object(ns, "_fabric_configured", return_value=True):
            return ns.search_open_ap(entity_ids=["81232"], statuses={"open"})

    def test_live_results_say_live(self):
        row = {"record_type": "Bill", "tranid": "1", "total": 5.0, "trandate": "2026-10-01"}
        result = self._search(lambda *a: [row])
        self.assertEqual((result["source"], result["row_count"], result["error"]), ("connect", 1, False))

    def test_a_failed_live_search_falls_back_to_the_copy_and_says_so(self):
        row = {"record_type": "Bill", "tranid": "2", "total": 5.0, "trandate": "2026-10-01"}
        result = self._search(RuntimeError("connect down"), lambda *a: [row])
        self.assertEqual((result["source"], result["row_count"]), ("fabric_fallback", 1))

    def test_both_failing_is_unavailable(self):
        result = self._search(RuntimeError("down"), RuntimeError("down too"))
        self.assertTrue(result["error"])

    def test_live_does_not_need_fabric_settings(self):
        with mock.patch.dict(os.environ, {"NETSUITE_SEARCH_SOURCE": "connect"}), \
                mock.patch.object(ns, "_run_search_connect", return_value=[]), \
                mock.patch.object(ns, "_fabric_configured", return_value=False):
            self.assertFalse(ns.search_open_ap(entity_ids=["81232"])["error"])

    def test_fetch_record_reads_live_then_falls_back(self):
        with mock.patch.dict(os.environ, {"NETSUITE_SEARCH_SOURCE": "connect"}), \
                mock.patch.object(ns, "_fetch_record_connect", return_value={"tranid": "MN847143"}) as live:
            self.assertEqual(ns.fetch_record("credit", "4739106"), {"tranid": "MN847143"})
        live.assert_called_once_with(ns.CREDIT_TABLE, "4739106")
        with mock.patch.dict(os.environ, {"NETSUITE_SEARCH_SOURCE": "connect"}), \
                mock.patch.object(ns, "_fetch_record_connect", side_effect=RuntimeError("down")), \
                mock.patch.object(ns, "execute_lakehouse_query", return_value=[]) as copy:
            self.assertIsNone(ns.fetch_record("credit", "4739106"))
        copy.assert_called_once()

    def test_live_search_has_one_time_limit_for_both_tables(self):
        # 2026-10-29: each query gets what is left of one search_timeout().
        client = mock.Mock()
        client.query.return_value = []
        with mock.patch.dict(os.environ, {"NETSUITE_SEARCH_TIMEOUT_SECONDS": "20"}), \
                mock.patch("src.netsuite.connect_client.get_shared_client", return_value=client):
            ns._run_search_connect(["81232"], None, None, {"open"}, None, None, None, 100)
        timeouts = [call.kwargs["timeout"] for call in client.query.call_args_list]
        self.assertEqual(len(timeouts), 2)
        self.assertTrue(0 < timeouts[1] <= timeouts[0] <= 20)

    def test_a_timed_out_live_search_falls_back_to_the_copy(self):
        from src.netsuite.connect_client import QueryTimeout
        row = {"record_type": "Bill", "tranid": "3", "total": 5.0, "trandate": "2026-10-01"}
        result = self._search(QueryTimeout("took over 25s"), lambda *a: [row])
        self.assertEqual((result["source"], result["row_count"], result["error"]), ("fabric_fallback", 1, False))

    def test_search_timeout_setting(self):
        for value, expected in (("", 25), ("40", 40), ("soon", 25), ("0", 25)):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"NETSUITE_SEARCH_TIMEOUT_SECONDS": value}):
                self.assertEqual(ns.search_timeout(), expected)

    def test_live_dates_are_turned_into_iso_text(self):
        from datetime import datetime
        client = mock.Mock()
        client.query.return_value = [{"id": 1, "tranid": "X", "trandate": datetime(2026, 9, 1), "duedate": None}]
        with mock.patch("src.netsuite.connect_client.get_shared_client", return_value=client):
            rows = ns._connect_rows("SELECT 1", [], ns.BILL_TABLE)
        self.assertEqual((rows[0]["trandate"], rows[0]["source_table"]), ("2026-09-01", ns.BILL_TABLE))


class AlreadyMatchedTests(unittest.TestCase):
    def test_lookup_returns_matched_records_by_type_and_id(self):
        rows = [{"netsuite_record_type": "credit", "netsuite_internal_id": "4677297", "statement_id": "STMT-7409AF91",
                 "invoice_number": "CM6303960-1", "status": "Matched", "matched_by": "system", "matched_at": "x"}]
        with mock.patch.object(queries, "execute_query", return_value=rows) as q:
            out = queries.get_matched_netsuite_records([("Credit", "4677297"), ("Bill", "bad id")])
        self.assertEqual(out[("credit", "4677297")]["invoice_number"], "CM6303960-1")
        self.assertEqual(q.call_args[0][1], ["Matched", "Matched manually", "4677297"])

    def test_no_usable_ids_means_no_query(self):
        with mock.patch.object(queries, "execute_query") as q:
            self.assertEqual(queries.get_matched_netsuite_records([("Bill", None)]), {})
        q.assert_not_called()

    def _render(self, rows, source="connect"):
        result = {"rows": rows, "row_count": len(rows), "truncated": False, "error": False,
                  "needs_filter": False, "message": None, "source": source}
        return templates.get_template("_netsuite_search_results.html").render(result=result, last_sync=None)

    def _row(self, **extra):
        return dict({"record_type": "Bill", "is_credit": False, "tranid": "338630", "internal_id": "77",
                     "vendor_name": "Gates", "total": 144.96, "trandate_display": "Sep 1, 2026",
                     "status_label": "Open", "already_matched": None}, **extra)

    def test_an_already_matched_record_is_marked_and_cannot_be_picked(self):
        html = self._render([self._row(already_matched={
            "invoice_number": "338630", "statement_id": "STMT-FA1403E1", "status": "Matched manually",
            "matched_by": "admin@vive.com", "matched_at": "2026-10-20T14:22:34"})])
        self.assertIn("✓ Already matched to 338630 · STMT-FA1403E1", html)
        self.assertIn("disabled", html)
        self.assertIn("Matched by hand by admin@vive.com", html)

    def test_already_matched_records_are_hidden_by_default_with_a_show_toggle(self):
        matched = self._row(tranid="338630", already_matched={
            "invoice_number": "338630", "statement_id": "STMT-FA1403E1", "status": "Matched",
            "matched_by": "system", "matched_at": "2026-10-20"})
        result = {"rows": [matched, self._row(tranid="111", internal_id="88")], "row_count": 2,
                  "truncated": False, "error": False, "needs_filter": False, "message": None,
                  "source": "connect", "matched_count": 1}
        html = templates.get_template("_netsuite_search_results.html").render(result=result, last_sync=None)
        self.assertIn('data-matched="1" hidden', html)
        self.assertIn("1 already matched record hidden", html)
        self.assertIn('class="ns-show-matched"', html)
        self.assertIn("1 result<", html)

    def test_when_everything_is_matched_the_panel_says_so(self):
        matched = self._row(already_matched={"invoice_number": "1", "statement_id": "S", "status": "Matched",
                                             "matched_by": "system", "matched_at": None})
        result = {"rows": [matched], "row_count": 1, "truncated": False, "error": False,
                  "needs_filter": False, "message": None, "source": "connect", "matched_count": 1}
        html = templates.get_template("_netsuite_search_results.html").render(result=result, last_sync=None)
        self.assertIn("Everything found is already matched", html)

    def test_an_unmatched_record_can_be_picked(self):
        html = self._render([self._row()])
        self.assertNotIn("Already matched", html)
        self.assertNotIn("disabled", html)

    def test_the_panel_says_where_the_rows_came_from(self):
        self.assertIn("Live NetSuite", self._render([self._row()], "connect"))
        self.assertIn("Live NetSuite unavailable", self._render([self._row()], "fabric_fallback"))
        self.assertIn("NetSuite data as of", self._render([self._row()], "fabric"))


if __name__ == "__main__":
    unittest.main()
