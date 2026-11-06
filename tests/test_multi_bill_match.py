"""
tests/test_multi_bill_match.py

Split payments (2026-11-06): on the exception review page a person can tick
SEVERAL NetSuite bills and/or credits for one statement invoice -- e.g. two
$50 bills for a $100 invoice, or a $150 bill and a $50 credit. They don't
have to add up: the difference is shown and saved. Paid bills can be picked
(the page warns). One Undo removes the whole group.

  * recon table: one Matched-manually row per line and record, all under the
    invoice (src/lakehouse/recon_table.py accept_manual_match / net_amount);
  * NetSuite: every record reconciled with Matched Bill = the invoice; the
    Statement Line points at all of them (Multiple Select) or the first (single
    link) -- and nothing is written if any record can't be found;
  * the route takes repeated `picks` fields "bill:123";
  * the review list and the Reconciliation tab show the invoice / line once.
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse import recon_table as rt
from src.netsuite import manual_match as mm
from src.netsuite import matched_bill_field as mbf
from src.netsuite.fields import MATCHED_BILL_FIELD
from test_accept_match import EXCEPTION, LINES, RESULTS, STATEMENT, TestRoutes as _RouteBase, _Db
from test_matched_bill_field import FakeNetSuite
from web import queries
from web import statement_processing as sp
from web.deps import templates
from web.routers import exceptions

BILL_A = {"record_type": "Bill", "internal_id": "501", "tranid": "INV567", "entity_id": "81667", "total": 50.0}
BILL_B = {"record_type": "Bill", "internal_id": "502", "tranid": "INV345", "entity_id": "81667", "total": 50.0}
BILL_150 = {"record_type": "Bill", "internal_id": "503", "tranid": "INV150", "entity_id": "81667", "total": 150.0}
CREDIT_50 = {"record_type": "Credit", "internal_id": "601", "tranid": "CM50", "entity_id": "81667", "total": 50.0}


class TestNetAmount(unittest.TestCase):
    def test_one_kind_adds_up(self):
        self.assertEqual(rt.net_amount([BILL_A, BILL_B], 100.0), 100.0)
        self.assertEqual(rt.match_difference([BILL_A, BILL_B], 100.0), 0.0)
        self.assertEqual(rt.match_difference([BILL_A], 100.0), 50.0)

    def test_bill_minus_credit_on_a_charge_line(self):
        self.assertEqual(rt.net_amount([BILL_150, CREDIT_50], 100.0), 100.0)
        self.assertEqual(rt.match_difference([BILL_150, CREDIT_50], 100.0), 0.0)

    def test_credit_minus_bill_on_a_credit_line(self):
        credit_150 = dict(CREDIT_50, internal_id="602", total=150.0)
        self.assertEqual(rt.net_amount([credit_150, BILL_A], -100.0), 100.0)
        self.assertEqual(rt.match_difference([credit_150, BILL_A], -100.0), 0.0)

    def test_single_record_is_unchanged(self):
        self.assertEqual(rt.match_difference(BILL_A, 57.54), 7.54)
        self.assertEqual(rt.match_difference(CREDIT_50, -50.0), 0.0)

    def test_unknown_amount(self):
        self.assertIsNone(rt.net_amount([BILL_A, dict(BILL_B, total=None)], 100.0))


class TestReconTable(_Db):
    def _accept(self, records, amount=100.0):
        return rt.accept_manual_match("STMT-1", "INV123", "EXC-1", "Not Found in NetSuite", amount, records,
                                      "ap@vive.com", "split payment", vendor_id="CONICELLI_TOYOTA",
                                      vendor_name="Conicelli Toyota")

    def test_one_row_per_line_and_record_with_the_group_difference(self):
        rt.replace_auto_rows("STMT-1", rt.build_auto_rows(STATEMENT, LINES[:2], RESULTS))
        self.assertEqual(self._accept([BILL_A, BILL_B]), 4)          # 2 lines x 2 bills
        manual = self.rows(source="manual")
        self.assertEqual(sorted({(r["line_number"], r["netsuite_tranid"]) for r in manual}),
                         [(1, "INV345"), (1, "INV567"), (2, "INV345"), (2, "INV567")])
        self.assertEqual({r["difference"] for r in manual}, {0.0})
        self.assertEqual({r["is_active"] for r in self.rows(source="auto", invoice_number="INV123")}, {0})

    def test_listed_once_with_every_record(self):
        self._accept([BILL_150, CREDIT_50])
        listed = rt.manual_matches("STMT-1")
        self.assertEqual(len(listed), 1)
        self.assertEqual([(r["record_type"], r["tranid"]) for r in listed[0]["records"]],
                         [("bill", "INV150"), ("credit", "CM50")])
        self.assertEqual(listed[0]["net_amount"], 100.0)

    def test_undo_removes_the_whole_group(self):
        rt.replace_auto_rows("STMT-1", rt.build_auto_rows(STATEMENT, LINES[:2], RESULTS))
        self._accept([BILL_A, BILL_B])
        undone = rt.undo_manual_match("STMT-1", "INV123", "lead@vive.com")
        self.assertEqual(undone["tranid"], "INV567, INV345")
        self.assertEqual({r["is_active"] for r in self.rows(source="manual")}, {0})
        self.assertEqual({(r["is_active"], r["status"]) for r in self.rows(source="auto", invoice_number="INV123")},
                         {(1, "Not found in NetSuite")})

    def test_a_record_matched_elsewhere_refuses_the_whole_group(self):
        rt.replace_auto_rows("STMT-1", rt.build_auto_rows(STATEMENT, LINES, RESULTS))   # L3 matched to bill 9123
        taken = dict(BILL_B, internal_id="9123", tranid="23")
        with self.assertRaisesRegex(rt.MatchConflict, "bill 23 is already matched to invoice INV900"):
            self._accept([BILL_A, taken])
        self.assertEqual(self.rows(source="manual"), [])

    def test_repeated_or_empty_picks_are_refused(self):
        with self.assertRaisesRegex(ValueError, "picked twice"):
            self._accept([BILL_A, dict(BILL_A)])
        with self.assertRaisesRegex(ValueError, "at least one"):
            self._accept([])
        with self.assertRaisesRegex(ValueError, "At most"):
            self._accept([dict(BILL_A, internal_id=str(i)) for i in range(rt.MAX_RECORDS + 1)])
        self.assertEqual(self.rows(source="manual"), [])

    def test_the_bills_show_as_already_matched(self):
        self._accept([BILL_A, BILL_B])
        with mock.patch.object(queries, "execute_query",
                               lambda sql, p=None: [dict(r) for r in self.conn.execute(sql, p or []).fetchall()]):
            matched = queries.get_matched_netsuite_records([("bill", "501"), ("bill", "502"), ("bill", "999")])
        self.assertEqual(sorted(matched), [("bill", "501"), ("bill", "502")])


class TestReconciliationTab(unittest.TestCase):
    def test_a_line_matched_to_two_bills_shows_once(self):
        base = {"statement_line_id": "L1", "line_number": 1, "invoice_number": "INV123", "line_amount": 100.0,
                "status": "Matched manually", "source": "manual", "exception_id": "EXC-1", "difference": 0.0,
                "matched_by": "ap@vive.com", "matched_at": "2026-11-06"}
        rows = [dict(base, netsuite_record_type="bill", netsuite_internal_id="501", netsuite_tranid="INV567",
                     netsuite_amount=50.0),
                dict(base, netsuite_record_type="bill", netsuite_internal_id="502", netsuite_tranid="INV345",
                     netsuite_amount=50.0),
                {"statement_line_id": "L2", "line_number": 2, "invoice_number": "INV900", "line_amount": 10.0,
                 "status": "Matched", "source": "auto", "netsuite_amount": 10.0}]
        view = sp.recon_view(rows)
        lines = view["rows"] if "rows" in view else view["lines"]
        self.assertEqual([l["line_number"] for l in lines], [1, 2])
        self.assertEqual(lines[0]["label"], "Matched manually to INV567, INV345")
        self.assertEqual(lines[0]["netsuite_amount"], 100.0)


class TestNetSuiteWrite(unittest.TestCase):
    def setUp(self):
        mbf.reset_cache()
        self.addCleanup(mbf.reset_cache)

    def _ns(self, mode):
        ns = FakeNetSuite(mode)
        ns.add_txn(501, "INV567", total=-50.0)
        ns.add_txn(502, "INV345", total=-50.0)
        ns.add_line(77, "STMT-1", "INV123", custrecord_sl_status="No match found",
                    custrecord_sl_exception_type="No match found", custrecord_sl_reconciled="F")
        return ns

    def _write(self, ns, records):
        with mock.patch.dict(os.environ, {"NETSUITE_WRITEBACK_ENABLED": "true", "NETSUITE_WRITEBACK_PDF_LINK": "false"}):
            return mm.write_manual_match("STMT-1", "INV123", 100.0, records, ["81667"], ns=ns, today="2026-11-06")

    def test_multiple_select_points_at_every_bill(self):
        ns = self._ns(mbf.MULTIPLE)
        out = self._write(ns, [BILL_A, BILL_B])
        self.assertEqual(out["status"], "written", out["detail"])
        for bid in ("501", "502"):
            self.assertEqual((ns.txns[bid]["custbody_reconciled"], ns.txns[bid][MATCHED_BILL_FIELD]), ("T", "INV123"))
        self.assertEqual(ns.lines["77"][mbf.FIELD], "501, 502")
        self.assertEqual(ns.lines["77"]["custrecord_sl_status"], "Matched")

    def test_single_link_keeps_the_first_bill_and_still_reconciles_both(self):
        ns = self._ns(mbf.SINGLE)
        out = self._write(ns, [BILL_A, BILL_B])
        self.assertEqual(out["status"], "written", out["detail"])
        self.assertEqual(ns.lines["77"][mbf.FIELD], "501")
        self.assertEqual({ns.txns[b]["custbody_reconciled"] for b in ("501", "502")}, {"T"})

    def test_nothing_is_written_when_one_record_is_missing(self):
        ns = self._ns(mbf.MULTIPLE)
        out = self._write(ns, [BILL_A, dict(BILL_B, tranid="NOPE")])
        self.assertEqual(out["status"], "not in sandbox")
        self.assertIn("nothing written", out["detail"])
        self.assertEqual([c for c in ns.calls if c[0] in ("PATCH", "POST")], [])

    def test_nothing_is_written_when_one_is_reconciled_by_another_statement(self):
        ns = self._ns(mbf.MULTIPLE)
        ns.txns["502"].update(custbody_reconciled="T", custbody_statement_reference="STMT-OTHER")
        out = self._write(ns, [BILL_A, BILL_B])
        self.assertEqual(out["status"], "reconciled by another statement")
        self.assertEqual([c for c in ns.calls if c[0] in ("PATCH", "POST")], [])

    def test_undo_puts_every_bill_and_the_line_back(self):
        ns = self._ns(mbf.MULTIPLE)
        before = json.loads(json.dumps({"txns": ns.txns, "lines": ns.lines}))
        out = self._write(ns, [BILL_A, BILL_B])
        with mock.patch.dict(os.environ, {"NETSUITE_WRITEBACK_ENABLED": "true"}):
            undone = mm.undo_manual_match_writes(out["before"], ns=ns)
        self.assertEqual(undone["status"], "undone", undone["detail"])
        for bid in ("501", "502"):
            self.assertEqual(ns.txns[bid]["custbody_reconciled"], "F")
            self.assertIsNone(ns.txns[bid].get(MATCHED_BILL_FIELD))
        self.assertIsNone(ns.lines["77"][mbf.FIELD])
        self.assertEqual(ns.lines["77"]["custrecord_sl_status"], before["lines"]["77"]["custrecord_sl_status"])

    def test_a_created_line_lists_every_bill(self):
        ns = self._ns(mbf.MULTIPLE)
        ns.lines.clear()
        out = self._write(ns, [BILL_A, BILL_B])
        self.assertEqual(ns.lines[out["statement_line_id"]][mbf.FIELD], "501, 502")


class TestQueries(unittest.TestCase):
    def test_note_and_message_name_every_record(self):
        calls = []
        with mock.patch("src.lakehouse.recon_table.accept_manual_match", lambda *a, **k: calls.append(a[5])), \
                mock.patch.object(queries, "resolve_exception", lambda *a: calls.append(a[6])), \
                mock.patch("src.validation.invoice_location.refresh_and_sync_quietly", lambda *_: None), \
                mock.patch.object(queries, "_write_manual_match_to_netsuite", lambda *a: {"status": "written"}):
            queries.accept_manual_match(EXCEPTION, [BILL_150, CREDIT_50], "Conicelli Toyota", "ap@vive.com")
        self.assertEqual(calls, [[BILL_150, CREDIT_50], "Matched to NetSuite bill INV150, credit CM50"])


class TestRoute(_RouteBase):
    def test_several_picks_are_each_re_read(self):
        form = dict(self.form, picks=["bill:501", "credit:601", "bill:501"])
        form.pop("record_type"); form.pop("internal_id")
        fetched = []

        def fetch(kind, rid):
            fetched.append((kind, rid))
            return {"bill:501": BILL_A, "credit:601": CREDIT_50}[f"{kind}:{rid}"]
        resp, accept = self._post(form=form, fetch=fetch)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(fetched, [("bill", "501"), ("credit", "601")])        # the repeat is dropped
        accept.assert_called_once_with(EXCEPTION, [BILL_A, CREDIT_50], "Conicelli Toyota", "ap@vive.com", "ok")
        self.assertIn("bill+INV567%2C+credit+CM50", resp.headers["location"])

    def test_one_missing_record_matches_nothing(self):
        form = dict(self.form, picks=["bill:501", "bill:502"])
        resp, accept = self._post(form=form, fetch=lambda k, r: BILL_A if r == "501" else None)
        self.assertIn("one+of+the+picked+records+%28bill+502%29+no+longer+exists", resp.headers["location"])
        accept.assert_not_called()

    def test_no_picks(self):
        form = {k: v for k, v in self.form.items() if k not in ("record_type", "internal_id")}
        resp, accept = self._post(form=form)
        self.assertIn("pick+at+least+one", resp.headers["location"])
        accept.assert_not_called()

    def test_too_many_picks(self):
        form = dict(self.form, picks=[f"bill:{i}" for i in range(rt.MAX_RECORDS + 1)])
        resp, accept = self._post(form=form)
        self.assertIn("at+most", resp.headers["location"])
        accept.assert_not_called()


class TestMarkup(unittest.TestCase):
    def test_review_list_shows_every_record_of_a_split_payment(self):
        from test_accept_match import TestMarkup as Base
        html = Base._render(Base(), manual_matches=[{
            "invoice_number": "INV123", "statement_id": "STMT-1", "netsuite_tranid": "INV150",
            "netsuite_record_type": "bill", "netsuite_amount": 150.0, "difference": 0.0, "net_amount": 100.0,
            "records": [{"record_type": "bill", "tranid": "INV150", "total": 150.0},
                        {"record_type": "credit", "tranid": "CM50", "total": 50.0}],
            "matched_by": "ap@vive.com", "matched_at": None}])
        self.assertIn("matches 2 NetSuite records", html)
        self.assertIn("bill INV150 $150.00, credit CM50 $50.00", html)
        self.assertIn("Together $100.00", html)

    def test_bar_has_room_for_several_picks_and_a_paid_warning(self):
        from test_accept_match import TestMarkup as Base
        html = Base._render(Base())
        for marker in ('id="nsPickList"', 'id="nsPickPaidWarn"', 'id="nsAcceptPicks"', 'id="nsConfirmList"',
                       'data-statement-signed="-50.51"'):
            self.assertIn(marker, html)

    def test_results_carry_the_status_for_the_paid_warning(self):
        row = {"record_type": "Bill", "is_credit": False, "tranid": "B1", "internal_id": "5", "vendor_name": "V",
               "entity_id": "1", "total": 12.5, "trandate": "9/1/2026", "trandate_display": "Sep 1, 2026",
               "duedate": None, "duedate_display": "", "status_label": "Paid In Full", "ro_number": None,
               "location_code": "64", "location_name": "Lamon", "transaction_number": "VENDBILL1"}
        html = templates.get_template("_netsuite_search_results.html").render(
            result={"rows": [row], "row_count": 1, "truncated": False, "error": False, "needs_filter": False,
                    "message": None}, last_sync=None)
        self.assertIn('data-status="Paid In Full"', html)
        self.assertNotIn("<form", html)


if __name__ == "__main__":
    unittest.main()
