"""
tests/test_accept_match.py

"Accept as match" (2026-10-19): on the exception review page a person picks
a NetSuite bill/credit in the Find in NetSuite panel and accepts it. The
recon table gets "Matched manually" rows for the invoice's lines (its auto
rows go inactive), the exception is resolved, and Undo reverses both. The
server re-reads the picked record by internal id; NetSuite itself is not
written in this step.
"""

import os
import sqlite3
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from src.lakehouse import recon_table as rt
from src.lakehouse.migrations import apply_pending_migrations
from src.matching import netsuite_search as ns
from web import queries
from web.deps import require_login, templates
from web.routers import exceptions
from web.routers.exceptions import REASON_BADGE, SEARCHABLE_REASONS

STATEMENT = {"statement_id": "STMT-1", "vendor_id": "CONICELLI_TOYOTA", "vendor_name": "Conicelli Toyota",
             "statement_period": "2026-10"}
BILL_23 = {"record_type": "Bill", "internal_id": "9123", "tranid": "23", "transaction_number": "VENDBILL23",
           "entity_id": "81667", "location_code": "64", "total": 57.54}
LINES = [
    {"statement_line_id": "L1", "line_number": 1, "invoice_number": "INV123", "charge_amount": 50.51},
    {"statement_line_id": "L2", "line_number": 2, "invoice_number": "INV123", "payment_amount": 5.0},
    {"statement_line_id": "L3", "line_number": 3, "invoice_number": "INV900", "charge_amount": 10.0},
]
RESULTS = {
    "L1": {"invoice_number": "INV123", "status": "Not found in NetSuite", "statement_amount": 50.51,
           "exception_id": "EXC-1", "exception_reason": "Not Found in NetSuite"},
    "L2": {"invoice_number": "INV123", "status": "Not found in NetSuite", "statement_amount": 50.51,
           "exception_id": "EXC-1", "exception_reason": "Not Found in NetSuite"},
    "L3": {"invoice_number": "INV900", "status": "Matched", "statement_amount": 10.0,
           "netsuite": {"record_type": "bill", "id": 9123, "tranid": "23", "amount": 10.0}},
}


class _Shared:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


class _Db(unittest.TestCase):

    def setUp(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        apply_pending_migrations(conn)
        self.conn = conn
        shared = _Shared(conn)

        def execute_sql(sql, params=None):
            cur = conn.execute(sql, params or [])
            conn.commit()
            return cur

        def execute_query(sql, params=None):
            return [dict(r) for r in conn.execute(sql, params or []).fetchall()]

        for name, fn in (("get_connection", lambda: shared), ("execute_sql", execute_sql),
                         ("execute_query", execute_query)):
            patcher = mock.patch.object(rt, name, fn)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(conn.close)

    def rows(self, **where):
        sql = "SELECT * FROM recon"
        if where:
            sql += " WHERE " + " AND ".join(f"{k} = ?" for k in where)
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY source, line_number", list(where.values()))]


class TestReconAcceptAndUndo(_Db):

    def _accept(self, record=BILL_23, invoice="INV123", statement_id="STMT-1"):
        return rt.accept_manual_match(statement_id, invoice, "EXC-1", "Not Found in NetSuite", 50.51, record,
                                      "ap@vive.com", "vendor confirmed", vendor_id="CONICELLI_TOYOTA",
                                      vendor_name="Conicelli Toyota")

    def test_accept_adds_a_manual_row_per_line_and_hides_the_auto_rows(self):
        rt.replace_auto_rows("STMT-1", rt.build_auto_rows(STATEMENT, LINES[:2], RESULTS))
        self.assertEqual(self._accept(record=dict(BILL_23, internal_id="7777", tranid="777")), 2)
        manual = self.rows(source="manual")
        self.assertEqual([(r["line_number"], r["status"], r["netsuite_tranid"], r["netsuite_internal_id"])
                          for r in manual], [(1, "Matched manually", "777", "7777"), (2, "Matched manually", "777", "7777")])
        self.assertEqual({(r["difference"], r["matched_by"], r["note"], r["exception_id"]) for r in manual},
                         {(-7.03, "ap@vive.com", "vendor confirmed", "EXC-1")})
        self.assertEqual({r["is_active"] for r in self.rows(source="auto", invoice_number="INV123")}, {0})

    def test_accept_without_auto_rows_still_records_the_match(self):
        self.assertEqual(self._accept(record=dict(BILL_23, internal_id="7777")), 1)
        row = self.rows(source="manual")[0]
        self.assertEqual((row["vendor_id"], row["invoice_number"], row["line_number"]),
                         ("CONICELLI_TOYOTA", "INV123", None))

    def test_a_bill_already_matched_elsewhere_is_refused(self):
        rt.replace_auto_rows("STMT-1", rt.build_auto_rows(STATEMENT, LINES, RESULTS))
        with self.assertRaisesRegex(rt.MatchConflict, "already matched to invoice INV900 on STMT-1"):
            self._accept()
        self.assertEqual(self.rows(source="manual"), [])

    def test_a_second_manual_match_for_the_invoice_is_refused(self):
        self._accept(record=dict(BILL_23, internal_id="7777"))
        with self.assertRaises(ValueError):
            self._accept(record=dict(BILL_23, internal_id="8888"))

    def test_undo_keeps_history_and_restores_the_auto_rows(self):
        rt.replace_auto_rows("STMT-1", rt.build_auto_rows(STATEMENT, LINES[:2], RESULTS))
        self._accept(record=dict(BILL_23, internal_id="7777", tranid="777"))
        undone = rt.undo_manual_match("STMT-1", "INV123", "lead@vive.com")
        self.assertEqual(undone, {"exception_ids": ["EXC-1"], "tranid": "777"})
        manual = self.rows(source="manual")
        self.assertEqual({(r["is_active"], r["undone_by"]) for r in manual}, {(0, "lead@vive.com")})
        auto = self.rows(source="auto", invoice_number="INV123")
        self.assertEqual({(r["is_active"], r["status"]) for r in auto}, {(1, "Not found in NetSuite")})
        self.assertEqual(rt.undo_manual_match("STMT-1", "INV123", "x"), {})

    def test_rerun_keeps_an_active_manual_match(self):
        rt.replace_auto_rows("STMT-1", rt.build_auto_rows(STATEMENT, LINES[:2], RESULTS))
        self._accept(record=dict(BILL_23, internal_id="7777"))
        rt.replace_auto_rows("STMT-1", rt.build_auto_rows(STATEMENT, LINES[:2], RESULTS))
        self.assertEqual([r["status"] for r in self.rows(statement_id="STMT-1", is_active=1)],
                         ["Matched manually", "Matched manually"])

    def test_manual_matches_lists_one_per_invoice(self):
        rt.replace_auto_rows("STMT-1", rt.build_auto_rows(STATEMENT, LINES[:2], RESULTS))
        self._accept(record=dict(BILL_23, internal_id="7777", tranid="777"))
        listed = rt.manual_matches("STMT-1")
        self.assertEqual([(m["invoice_number"], m["netsuite_tranid"]) for m in listed], [("INV123", "777")])


EXCEPTION = {"exception_id": "EXC-1", "statement_id": "STMT-1", "invoice_number": "INV123",
             "exception_reason": "Not Found in NetSuite", "statement_amount": 50.51,
             "vendor_id": "CONICELLI_TOYOTA", "exception_status": "OPEN"}


class TestQueriesAcceptAndUndo(unittest.TestCase):

    def test_saves_the_match_first_then_resolves_with_the_match_in_the_note(self):
        calls = []
        with mock.patch("src.lakehouse.recon_table.accept_manual_match", lambda *a, **k: calls.append("recon")), \
                mock.patch.object(queries, "resolve_exception",
                                  lambda *a: calls.append(("resolve", a[5], a[6], a[7]))), \
                mock.patch.object(queries, "_write_manual_match_to_netsuite",
                                  lambda *a: calls.append("netsuite") or {"status": "written"}):
            result = queries.accept_manual_match(EXCEPTION, BILL_23, "Conicelli Toyota", "ap@vive.com", "confirmed")
        # Saved, then resolved, then (step c) written to NetSuite.
        self.assertEqual(calls, ["recon", ("resolve", "ACCEPTED", "Matched to NetSuite bill 23. confirmed", "ap@vive.com"),
                                 "netsuite"])
        self.assertEqual(result, {"status": "written"})

    def test_a_conflict_resolves_nothing(self):
        resolve, netsuite = mock.Mock(), mock.Mock()
        with mock.patch("src.lakehouse.recon_table.accept_manual_match", side_effect=rt.MatchConflict("taken")), \
                mock.patch.object(queries, "resolve_exception", resolve), \
                mock.patch.object(queries, "_write_manual_match_to_netsuite", netsuite):
            with self.assertRaises(rt.MatchConflict):
                queries.accept_manual_match(EXCEPTION, BILL_23, "Conicelli Toyota", "ap@vive.com")
        resolve.assert_not_called()
        netsuite.assert_not_called()

    def test_if_resolving_fails_the_match_is_undone(self):
        undo = mock.Mock()
        with mock.patch("src.lakehouse.recon_table.accept_manual_match"), \
                mock.patch("src.lakehouse.recon_table.undo_manual_match", undo), \
                mock.patch.object(queries, "resolve_exception", side_effect=RuntimeError("fabric down")):
            with self.assertRaises(RuntimeError):
                queries.accept_manual_match(EXCEPTION, BILL_23, "Conicelli Toyota", "ap@vive.com")
        undo.assert_called_once_with("STMT-1", "INV123", "ap@vive.com")

    def test_undo_reopens_each_exception_and_records_it(self):
        recon_sql, execute_sql, recompute = mock.Mock(), mock.Mock(), mock.Mock()
        with mock.patch("src.lakehouse.recon_table.undo_manual_match",
                        return_value={"exception_ids": ["EXC-1"], "tranid": "23"}), \
                mock.patch("src.lakehouse.recon_table.manual_writeback_before", return_value=None), \
                mock.patch.object(queries, "recon_sql", recon_sql), mock.patch.object(queries, "execute_sql", execute_sql), \
                mock.patch.object(queries, "_recompute_summary_counts", recompute):
            self.assertTrue(queries.undo_manual_match("STMT-1", "INV123", "Conicelli Toyota", "lead@vive.com"))
        self.assertIn("exception_status = 'OPEN'", recon_sql.call_args.args[0])
        self.assertEqual(recon_sql.call_args.args[1], ["EXC-1"])
        self.assertIn("'PENDING'", execute_sql.call_args.args[0])
        self.assertIn("Undo: manual match to NetSuite 23 removed", execute_sql.call_args.args[1])
        recompute.assert_called_once_with("STMT-1")

    def test_undo_with_nothing_to_undo(self):
        with mock.patch("src.lakehouse.recon_table.undo_manual_match", return_value={}), \
                mock.patch("src.lakehouse.recon_table.manual_writeback_before", return_value=None):
            self.assertFalse(queries.undo_manual_match("STMT-1", "INV123", "V", "u"))


class TestRoutes(unittest.TestCase):

    def setUp(self):
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="x")
        app.include_router(exceptions.router)
        app.dependency_overrides[require_login] = lambda: "ap@vive.com"
        self.client = TestClient(app)
        self.form = {"exception_id": "EXC-1", "record_type": "bill", "internal_id": "9123", "note": " ok ",
                     "statement_id": "STMT-1", "filter": "all", "sort": ""}

    def _post(self, **patches):
        with mock.patch.object(exceptions.queries, "get_recon_exception", patches.get("exception", lambda _: EXCEPTION)), \
                mock.patch.object(exceptions, "fetch_record", patches.get("fetch", lambda t, i: BILL_23)), \
                mock.patch.object(exceptions.queries, "accept_manual_match", patches.get("accept", mock.Mock())) as accept:
            resp = self.client.post("/exceptions/Conicelli%20Toyota/accept-match", data=self.form, follow_redirects=False)
        return resp, accept

    def test_accept_uses_the_re_read_record_and_redirects_back(self):
        resp, accept = self._post()
        self.assertEqual(resp.status_code, 303)
        self.assertTrue(resp.headers["location"].startswith("/exceptions/Conicelli%20Toyota?statement_id=STMT-1&match_msg="))
        self.assertIn("matched+to+NetSuite+bill+23", resp.headers["location"])
        accept.assert_called_once_with(EXCEPTION, BILL_23, "Conicelli Toyota", "ap@vive.com", "ok")

    def test_closed_exception_missing_record_and_conflict_match_nothing(self):
        resp, accept = self._post(exception=lambda _: dict(EXCEPTION, exception_status="RESOLVED"))
        self.assertIn("no+longer+open", resp.headers["location"]); accept.assert_not_called()
        resp, accept = self._post(fetch=lambda t, i: None)
        self.assertIn("wasn%27t+found", resp.headers["location"]); accept.assert_not_called()
        resp, _ = self._post(accept=mock.Mock(side_effect=rt.MatchConflict("bill 23 is already matched")))
        self.assertIn("Not+matched", resp.headers["location"])

    def test_undo_route(self):
        with mock.patch.object(exceptions.queries, "undo_manual_match", return_value=True) as undo:
            resp = self.client.post("/exceptions/Conicelli%20Toyota/undo-match",
                                    data={"invoice_number": "INV123", "statement_id": "STMT-1"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("undone", resp.headers["location"])
        undo.assert_called_once_with("STMT-1", "INV123", "Conicelli Toyota", "ap@vive.com")


class TestMarkup(unittest.TestCase):

    def _render(self, **extra):
        ctx = dict(
            active_page="exceptions", vendor_name="Conicelli Toyota", vendor_display_name="Conicelli Toyota",
            vendor_url_name="Conicelli%20Toyota", not_found=False, statement={"statement_id": "STMT-1"}, exceptions=[],
            selected={"exception_id": "EXC-1", "statement_id": "STMT-1", "invoice_number": "INV123", "vendor_id": "CT",
                      "statement_amount": -50.51, "erp_amount": None, "exception_reason": "Not Found in NetSuite",
                      "exception_status": "OPEN", "date_raised": None, "days_open": 1, "match_confidence": None,
                      "escalation_status": None, "invoice_date": None, "ro_number": None},
            total=2, resolved=1, progress_pct=50, filter="all", sort="", reason_badge=REASON_BADGE,
            high_confidence_count=0, bulk_approve_threshold=0.99, netsuite_record=None,
            searchable_reasons=SEARCHABLE_REASONS, shop_options=[], manual_matches=[], match_msg=None)
        ctx.update(extra)
        return templates.get_template("exceptions_review.html").render(**ctx)

    def test_accept_bar_and_dialog_sit_outside_the_look_only_panel(self):
        html = self._render()
        panel_end = html.index("</section>", html.index('<section class="ns-inline"'))
        self.assertGreater(html.index('id="nsAccept"'), panel_end)
        self.assertGreater(html.index('id="nsAcceptDialog"'), panel_end)
        self.assertLess(html.index('id="nsAcceptDialog"'), html.index('id="action-form"'))
        self.assertIn('action="/exceptions/Conicelli%20Toyota/accept-match"', html)
        self.assertIn('data-statement-amount="50.51"', html)

    def test_manual_matches_listed_with_undo_and_the_message_shown(self):
        html = self._render(manual_matches=[{"invoice_number": "INV777", "statement_id": "STMT-1",
                                             "netsuite_tranid": "23", "netsuite_record_type": "bill",
                                             "netsuite_amount": 57.54, "difference": -7.03,
                                             "matched_by": "ap@vive.com", "matched_at": None}],
                            match_msg="Invoice INV777 matched to NetSuite bill 23.")
        self.assertIn("Matched manually (1)", html)
        self.assertIn("Reconciled · matches 23", html)
        self.assertIn('action="/exceptions/Conicelli%20Toyota/undo-match"', html)
        self.assertIn('<div class="match-msg" role="status">Invoice INV777 matched to NetSuite bill 23.</div>', html)

    def test_results_rows_with_an_internal_id_get_a_pick_checkbox(self):
        row = {"record_type": "Credit", "is_credit": True, "tranid": "CM23", "internal_id": "555", "vendor_name": "V",
               "entity_id": "1", "total": 12.5, "trandate": "9/1/2026", "trandate_display": "Sep 1, 2026",
               "duedate": None, "duedate_display": "", "status_label": "Open", "ro_number": None,
               "location_code": "64", "location_name": "Lamon", "transaction_number": "VENDCRED1"}
        html = templates.get_template("_netsuite_search_results.html").render(
            result={"rows": [row], "row_count": 1, "truncated": False, "error": False, "needs_filter": False,
                    "message": None}, last_sync=None)
        self.assertIn('class="ns-pick"', html)
        self.assertIn('data-record-type="credit" data-internal-id="555"', html)
        self.assertIn('data-tranid="CM23" data-amount="12.50"', html)
        self.assertNotIn("<form", html)


class TestFetchRecord(unittest.TestCase):

    def test_bad_type_or_id_never_queries(self):
        with mock.patch.object(ns, "execute_lakehouse_query") as q:
            self.assertIsNone(ns.fetch_record("invoice", "1"))
            self.assertIsNone(ns.fetch_record("bill", "1; DROP"))
            q.assert_not_called()

    def test_reads_by_id_from_the_right_table(self):
        raw = {"source_table": ns.CREDIT_TABLE, "id": "555", "tranid": "CM23", "total": "12.5", "location": "64"}
        with mock.patch.object(ns, "execute_lakehouse_query", return_value=[raw]) as q:
            rec = ns.fetch_record("credit", "555")
        self.assertIn("FROM bronze.netsuite_vendorcredit", q.call_args.args[0])
        self.assertEqual(q.call_args.args[1], ["555"])
        self.assertEqual((rec["internal_id"], rec["record_type"], rec["total"]), ("555", "Credit", 12.5))


if __name__ == "__main__":
    unittest.main()
