"""
tests/test_bulk_clear.py

Bulk "Clear exception" (2026-11-12): tick several exceptions on a statement's
review page and clear them with one shared note. Each is cleared the same way
as one at a time (queries.clear_exceptions_bulk()); exceptions already
resolved, or on another statement, are skipped and counted.
"""

import os
import sys
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from web import queries
from web.deps import require_login
from web.routers import exceptions

SIDEBAR = {"get_open_recon_exceptions_count": lambda: 0, "get_pending_review_count": lambda: 0,
           "get_outlook_synced_jobs": lambda: []}


def _exc(eid, inv, status="OPEN", sid="S1", amount=10.0):
    return {"exception_id": eid, "statement_id": sid, "invoice_number": inv, "exception_status": status,
            "exception_reason": "Not Found in NetSuite", "statement_amount": amount, "vendor_id": "V",
            "match_confidence": None, "invoice_date": None, "erp_amount": None, "days_open": 1,
            "escalation_status": None, "ro_number": None}


EXC = {"E1": _exc("E1", "100"), "E2": _exc("E2", "200"), "E3": _exc("E3", "300", status="CLEARED"),
       "E4": _exc("E4", "400", sid="S2")}


def _client():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(exceptions.router)
    app.dependency_overrides[require_login] = lambda: "erin@vive.com"
    return TestClient(app)


def _message(resp):
    return parse_qs(urlparse(resp.headers["location"]).query)["match_msg"][0]


class BulkClearRouteTests(unittest.TestCase):

    def setUp(self):
        mock.patch("web.queries.get_recon_exception", lambda eid: EXC.get(eid)).start()
        self.bulk = mock.patch("web.queries.clear_exceptions_bulk",
                               side_effect=lambda excs, *a: [{"status": "written"} for _ in excs]).start()
        self.addCleanup(mock.patch.stopall)
        self.client = _client()

    def _post(self, ids, note="paid by check 1234", sid="S1"):
        return self.client.post("/exceptions/Acme/clear-bulk", follow_redirects=False,
                                data={"exception_ids": ids, "note": note, "statement_id": sid, "filter": "all"})

    def test_clears_the_open_ones_with_one_shared_note(self):
        resp = self._post(["E1", "E2"])
        self.assertEqual(resp.status_code, 303)
        cleared, vendor, user, note = self.bulk.call_args.args
        self.assertEqual([e["exception_id"] for e in cleared], ["E1", "E2"])
        self.assertEqual((vendor, user, note), ("Acme", "erin@vive.com", "paid by check 1234"))
        self.assertEqual(_message(resp), "2 exceptions cleared. NetSuite: 2 written.")
        self.assertIn("statement_id=S1", resp.headers["location"])

    def test_already_resolved_and_other_statements_are_skipped(self):
        resp = self._post(["E1", "E3", "E4", "NOPE"])
        self.assertEqual([e["exception_id"] for e in self.bulk.call_args.args[0]], ["E1"])
        self.assertEqual(_message(resp),
                         "1 exception cleared. NetSuite: 1 written. "
                         "3 skipped (already resolved, or not on this statement).")

    def test_a_note_is_required(self):
        resp = self._post(["E1"], note="  ")
        self.bulk.assert_not_called()
        self.assertIn("add a note", _message(resp))

    def test_nothing_selected(self):
        resp = self._post([])
        self.bulk.assert_not_called()
        self.assertIn("no exceptions were selected", _message(resp))

    def test_no_limit(self):
        many = {f"X{i}": _exc(f"X{i}", str(1000 + i)) for i in range(120)}
        with mock.patch("web.queries.get_recon_exception", lambda eid: many.get(eid)):
            resp = self._post(list(many))
        self.assertEqual(len(self.bulk.call_args.args[0]), 120)
        self.assertTrue(_message(resp).startswith("120 exceptions cleared."))


class ClearExceptionsBulkTests(unittest.TestCase):

    def test_each_is_resolved_then_flag_removed_and_outcome_saved(self):
        calls = []
        with mock.patch("web.queries.resolve_exception", side_effect=lambda *a: calls.append(("resolve", a[0]))), \
                mock.patch("web.queries._statement_entity_ids", return_value=["123"]), \
                mock.patch("src.netsuite.clear_exception.clear_exception_writes",
                           side_effect=lambda sid, inv, ids: {"status": "written", "inv": inv}), \
                mock.patch("src.lakehouse.recon_table.set_clear_writeback",
                           side_effect=lambda sid, inv, r: calls.append(("saved", inv))):
            results = queries.clear_exceptions_bulk([EXC["E1"], EXC["E2"]], "Acme", "erin@vive.com", "note")
        self.assertEqual([r["inv"] for r in results], ["100", "200"])
        self.assertEqual(calls, [("resolve", "E1"), ("resolve", "E2"), ("saved", "100"), ("saved", "200")])

    def test_a_netsuite_failure_is_reported_not_raised(self):
        with mock.patch("web.queries.resolve_exception"), \
                mock.patch("web.queries._statement_entity_ids", return_value=["123"]), \
                mock.patch("src.netsuite.clear_exception.clear_exception_writes", side_effect=RuntimeError("down")), \
                mock.patch("src.lakehouse.recon_table.set_clear_writeback"):
            results = queries.clear_exceptions_bulk([EXC["E1"]], "Acme", "erin@vive.com", "note")
        self.assertIn("down", results[0]["error"])


class ReviewPageTests(unittest.TestCase):

    def test_checkboxes_select_all_and_dialog(self):
        statement = {"statement_id": "S1", "vendor_name": "Acme", "source_file": "s1.pdf"}
        fns = {**SIDEBAR,
               "get_statement_by_id": lambda sid: statement,
               "get_open_exceptions": lambda sid, f=None, s=None: [EXC["E1"], EXC["E2"]],
               "get_exception_counts": lambda sid: (2, 0),
               "get_statement_shop": lambda sid: None,
               "get_manual_matches": lambda sid: [],
               "get_cleared_exceptions": lambda sid: []}
        for name, fn in fns.items():
            mock.patch(f"web.queries.{name}", fn).start()
        mock.patch("web.routers.exceptions._writeback_status", lambda sid: None).start()
        mock.patch("web.routers.exceptions._statement_pdf_url", lambda sid: None).start()
        mock.patch("web.routers.exceptions.shop_options", lambda: []).start()
        mock.patch("web.statement_completion.history", lambda sid: []).start()
        mock.patch("web.statement_completion.current_status", lambda sid: None).start()
        self.addCleanup(mock.patch.stopall)
        html = _client().get("/exceptions/Acme?statement_id=S1").text
        self.assertEqual(html.count('class="bulk-check"'), 2)
        self.assertIn('id="bulkAll"', html)
        self.assertIn('action="/exceptions/Acme/clear-bulk"', html)
        self.assertIn("Note for all of them", html)


if __name__ == "__main__":
    unittest.main()
