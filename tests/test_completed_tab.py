"""
tests/test_completed_tab.py

Completed (2026-11-11): a statement 100% reconciled -- validation passed and
no open exceptions (every line matched, or every exception resolved).
NetSuite write-back is not part of it. Statement Processing gets a
"Completed" chip; the Exceptions page gets All / Open / Completed tabs
(default All). Completed cards carry a green border and a "Completed" tag.
"""

import os
import sqlite3
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from web import statement_completion as completion
from web import statement_processing as sp
from web.deps import require_login
from web.routers import exceptions


def _intake(sid="S1", status="matches"):
    return {"statement_id": sid, "source_file": f"{sid}.pdf", "vendor_name": "Conicelli Toyota",
            "statement_period": "2026-10", "statement_total_as_printed": 100.0, "validation_status": status,
            "validation_difference": 0.0, "validation_method": "primary",
            "ingestion_timestamp": "2026-11-10T10:00:00+00:00", "shop": "Albany", "passed": status == "matches"}


class TestCompletedCard(unittest.TestCase):

    def test_every_line_matched_is_completed(self):
        self.assertTrue(sp.intake_card(_intake(), recon={"exceptions": 0, "reasons": {}})["completed"])

    def test_every_exception_resolved_is_completed(self):
        card = sp.intake_card(_intake(), recon={"exceptions": 0, "reasons": {}, "resolved": 3})
        self.assertTrue(card["completed"])

    def test_one_open_exception_is_not(self):
        card = sp.intake_card(_intake(), recon={"exceptions": 1, "reasons": {"Appears to be Paid": 1}})
        self.assertFalse(card["completed"])

    def test_failed_validation_is_not_even_with_no_exceptions(self):
        card = sp.intake_card(_intake(status="mismatch"), recon={"exceptions": 0, "reasons": {}})
        self.assertFalse(card["completed"])

    def test_not_reconciled_yet_is_not(self):
        self.assertFalse(sp.intake_card(_intake())["completed"])
        running = sp.intake_card(_intake(), job={"job_id": "J1", "status": "PROCESSING"})
        self.assertFalse(running["completed"])

    def test_job_cards_are_never_completed(self):
        card = sp.job_card({"job_id": "J1", "status": "FAILED", "error_message": "x",
                            "submitted_at": "2026-11-10T10:00:00+00:00"})
        self.assertFalse(card["completed"])


SIDEBAR = {"get_open_recon_exceptions_count": lambda: 0, "get_pending_review_count": lambda: 0,
           "get_outlook_synced_jobs": lambda: []}


def _client(router):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(router)
    app.dependency_overrides[require_login] = lambda: "tester"
    return TestClient(app)


class TestStatementProcessingPage(unittest.TestCase):

    def tearDown(self):
        mock.patch.stopall()

    def test_completed_chip_and_tag(self):
        from web.routers import validation
        fns = {**SIDEBAR,
               "get_validation_report": lambda: [_intake("S1"), _intake("S2")],
               "get_processing_jobs": lambda: [],
               "get_recon_status": lambda: {"S1": {"exceptions": 0, "reasons": {}},
                                            "S2": {"exceptions": 2, "reasons": {"Amount Mismatch": 2}}}}
        for name, fn in fns.items():
            mock.patch(f"web.queries.{name}", fn).start()
        mock.patch("web.statement_completion.all_marked", lambda: {}).start()
        mock.patch("web.statement_completion.all_statuses", lambda: {}).start()
        mock.patch("web.statement_completion.edited_ids", lambda: set()).start()
        html = _client(validation.router).get("/validation").text
        self.assertIn('data-filter="completed">Completed (<span id="completed-count">', html)
        self.assertEqual(html.count('data-completed="1"'), 1)
        self.assertEqual(html.count('sp-card is-completed'), 1)
        self.assertEqual(html.count('class="completed-tag"'), 1)
        # Exceptions is the default (the script starts on it; no chip is pre-set).
        self.assertIn('var currentStatus = "exceptions";', html)
        self.assertIn('<option value="exceptions-new">New</option>', html)
        self.assertIn('<option value="exceptions-progress">In progress</option>', html)
        self.assertIn('id="followup-filter"', html)
        self.assertIn('data-stage="new"', html)

    def test_resolved_followup_or_pdf_edit_makes_it_in_progress(self):
        from web.routers import validation
        fns = {**SIDEBAR,
               "get_validation_report": lambda: [_intake("A"), _intake("B"), _intake("C"), _intake("D")],
               "get_processing_jobs": lambda: [],
               "get_recon_status": lambda: {sid: {"exceptions": 2, "reasons": {}} for sid in "ABCD"},
               "get_recon_card_status": lambda: {"B": {"exceptions": 1, "reasons": {}, "resolved": 1, "matched": 0}}}
        for name, fn in fns.items():
            mock.patch(f"web.queries.{name}", fn).start()
        mock.patch("web.statement_completion.all_marked", lambda: {}).start()
        mock.patch("web.statement_completion.all_statuses", lambda: {
            "C": {"statement_id": "C", "status": "sent_to_shop", "set_by": "x", "set_at": "", "label": "Sent to shop"}}).start()
        mock.patch("web.statement_completion.edited_ids", lambda: {"D"}).start()
        html = _client(validation.router).get("/validation").text
        self.assertEqual(html.count('data-stage="new"'), 1)
        self.assertEqual(html.count('data-stage="progress"'), 3)
        self.assertIn('data-followup="sent_to_shop"', html)


class TestWorkStage(unittest.TestCase):

    def test_new_until_anything_is_done(self):
        self.assertEqual(completion.work_stage(0, None, False), completion.NEW)
        self.assertEqual(completion.work_stage(1, None, False), completion.IN_PROGRESS)
        self.assertEqual(completion.work_stage(0, {"status": "sent_to_shop"}, False), completion.IN_PROGRESS)
        self.assertEqual(completion.work_stage(None, None, True), completion.IN_PROGRESS)


class TestExceptionsPage(unittest.TestCase):

    def setUp(self):
        def run(sid, exceptions_):
            return {"statement_id": sid, "vendor_name": "Fenix", "vendor_display_name": "Fenix", "shop": None,
                    "billing_location": None, "statement_period": "2026-10", "total_invoice_count": 5,
                    "matched_count": 5 - exceptions_, "exception_count": exceptions_, "statement_total": 100.0,
                    "overall_status": "", "reconciliation_timestamp": None, "reason_breakdown": {},
                    "aging": None}
        runs = [run("CLEAN", 0), run("OPEN", 2), run("CLEAN_BUT_FAILED_VALIDATION", 0)]
        fns = {**SIDEBAR,
               "get_exception_runs": lambda window=None: [dict(r) for r in runs],
               "get_run_timestamps": lambda: [datetime(2026, 11, 10, 12)],
               "get_validation_passed_ids": lambda: {"CLEAN", "OPEN"}}
        for name, fn in fns.items():
            mock.patch(f"web.queries.{name}", fn).start()
        mock.patch("web.routers.exceptions._attach_writeback_status").start()
        self.marked = {}
        mock.patch("web.statement_completion.all_marked", lambda: self.marked).start()
        self.statuses = {}
        mock.patch("web.statement_completion.all_statuses", lambda: self.statuses).start()
        mock.patch("web.statement_completion.edited_ids", lambda: set()).start()
        mock.patch("web.queries.get_recon_card_status", lambda: {}).start()
        self.addCleanup(mock.patch.stopall)

    def test_tabs_default_all_and_only_the_clean_passed_run_is_completed(self):
        html = _client(exceptions.router).get("/exceptions").text
        # Exceptions is the default tab, with New / In progress under it.
        self.assertIn('class="filter-chip sync-picker-btn active" id="exception-stage-btn"', html)
        self.assertIn('var currentTab = "open";', html)
        self.assertIn('<option value="open-new">New</option>', html)
        self.assertIn('class="filter-chip" data-tab="all"', html)
        self.assertEqual(html.count('data-stage="new"'), 3)
        self.assertIn('data-tab="completed"', html)
        self.assertEqual(html.count('data-completed="1"'), 1)
        self.assertEqual(html.count('class="completed-tag"'), 1)
        self.assertIn('href="/reports/CLEAN" class="vendor-card clean is-completed"', html)
        # Validation failed: no exceptions, but still "Reconciled", not Completed.
        self.assertIn('href="/reports/CLEAN_BUT_FAILED_VALIDATION" class="vendor-card clean"', html)

    def test_intake_log_unreadable_falls_back_to_the_exception_count(self):
        mock.patch("web.queries.get_validation_passed_ids", lambda: None).start()
        html = _client(exceptions.router).get("/exceptions").text
        self.assertEqual(html.count('data-completed="1"'), 2)

    def test_a_marked_statement_with_open_exceptions_is_completed(self):
        self.marked = {"OPEN": {"statement_id": "OPEN", "action": "completed", "done_by": "erin@vive.com",
                                "done_at": "2026-11-11T10:00:00+00:00", "note": None}}
        html = _client(exceptions.router).get("/exceptions").text
        self.assertEqual(html.count('data-completed="1"'), 2)
        self.assertIn("Marked complete by erin@vive.com", html)
        # Its open exceptions still show.
        self.assertIn("2 exceptions", html)

    def test_follow_up_tag_and_filter(self):
        self.statuses = {"OPEN": {"statement_id": "OPEN", "status": "sent_to_shop", "set_by": "erin@vive.com",
                                  "set_at": "2026-11-11T10:00:00+00:00", "label": "Sent to shop"}}
        html = _client(exceptions.router).get("/exceptions").text
        self.assertIn('id="status-filter"', html)
        self.assertIn('<option value="waiting_to_post">Waiting to post</option>', html)
        self.assertIn('data-status="sent_to_shop"', html)
        self.assertEqual(html.count('data-status="none"'), 2)
        self.assertIn('class="followup-tag" title="Set by erin@vive.com', html)


class _SqliteTable(unittest.TestCase):
    """statement_completion_log in an in-memory SQLite."""

    def setUp(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row

        def query(sql, params=None):
            return [dict(r) for r in self.db.execute(sql, params or []).fetchall()]

        def execute(sql, params=None):
            self.db.execute(sql, params or [])
            self.db.commit()

        mock.patch("web.queries.execute_query", query).start()
        mock.patch("web.queries.execute_sql", execute).start()
        mock.patch("web.statement_completion._using_azure_sql", lambda: False).start()
        mock.patch.dict(completion._TABLE_READY, {"done": False}).start()
        mock.patch.dict(completion._STATUS_TABLE_READY, {"done": False}).start()
        self.addCleanup(mock.patch.stopall)


class TestCompletionLog(_SqliteTable):

    def test_mark_unmark_and_who(self):
        self.assertIsNone(completion.marked("S1"))
        completion.set_completed("S1", True, "erin@vive.com")
        self.assertEqual(completion.marked("S1")["done_by"], "erin@vive.com")
        self.assertEqual(set(completion.all_marked()), {"S1"})
        completion.set_completed("S1", False, "jenn@vive.com")
        self.assertIsNone(completion.marked("S1"))
        self.assertEqual(completion.all_marked(), {})
        log = completion.history("S1")
        self.assertEqual([(r["action"], r["done_by"]) for r in log],
                         [("reopened", "jenn@vive.com"), ("completed", "erin@vive.com")])
        self.assertTrue(all(r["done_at"] for r in log))


class TestReviewPageCheckbox(_SqliteTable):

    def setUp(self):
        super().setUp()
        statement = {"statement_id": "S1", "vendor_name": "Douglas Infiniti", "source_file": "s1.pdf"}
        fns = {**SIDEBAR,
               "get_statement_by_id": lambda sid: statement if sid == "S1" else None,
               "get_open_exceptions": lambda sid, f=None, s=None: [],
               "get_exception_counts": lambda sid: (3, 1),
               "get_statement_shop": lambda sid: None,
               "get_manual_matches": lambda sid: [],
               "get_cleared_exceptions": lambda sid: []}
        for name, fn in fns.items():
            mock.patch(f"web.queries.{name}", fn).start()
        mock.patch("web.routers.exceptions._writeback_status", lambda sid: None).start()
        mock.patch("web.routers.exceptions._statement_pdf_url", lambda sid: None).start()
        mock.patch("web.routers.exceptions.shop_options", lambda: []).start()
        self.client = _client(exceptions.router)
        self.client.app.dependency_overrides[require_login] = lambda: "erin@vive.com"

    def _page(self):
        return self.client.get("/exceptions/Douglas%20Infiniti?statement_id=S1").text

    def test_tick_logs_the_user_and_untick_logs_again(self):
        page = self._page()
        self.assertIn('action="/exceptions/Douglas%20Infiniti/complete"', page)
        self.assertIn('data-open="2"', page)
        self.assertIn("stmt-btn stmt-btn-complete\"", page)
        self.assertIn("Mark complete", page)

        done = self.client.post("/exceptions/Douglas%20Infiniti/complete",
                                data={"statement_id": "S1", "completed": "1"}, follow_redirects=False)
        self.assertEqual(done.status_code, 303)
        self.assertIn("statement_id=S1", done.headers["location"])
        self.assertEqual(completion.marked("S1")["done_by"], "erin@vive.com")
        page = self._page()
        self.assertIn("stmt-btn stmt-btn-complete is-on", page)
        self.assertIn("by erin@vive.com", page)

        self.client.post("/exceptions/Douglas%20Infiniti/complete", data={"statement_id": "S1", "completed": ""})
        self.assertIsNone(completion.marked("S1"))
        page = self._page()
        self.assertNotIn("stmt-btn-complete is-on", page)
        self.assertNotIn("by erin@vive.com", page)
        # The untick stays in the log, with who did it.
        self.assertEqual(completion.history("S1")[0]["done_by"], "erin@vive.com")

    def test_unknown_statement_is_not_logged(self):
        resp = self.client.post("/exceptions/X/complete", data={"statement_id": "NOPE", "completed": "1"},
                                follow_redirects=False)
        self.assertIn("statement+not+found", resp.headers["location"])
        self.assertEqual(completion.history("NOPE"), [])

    def test_status_is_set_shown_with_who_and_cleared(self):
        page = self._page()
        self.assertIn('action="/exceptions/Douglas%20Infiniti/status"', page)
        self.assertIn(">Set follow-up</option>", page)
        self.assertIn("stmt-btn stmt-btn-followup sync-picker-btn", page)
        resp = self.client.post("/exceptions/Douglas%20Infiniti/status",
                                data={"statement_id": "S1", "status": "requested_copy"}, follow_redirects=False)
        self.assertIn("Requested+copy+from+vendor", resp.headers["location"])
        page = self._page()
        self.assertIn('<option value="requested_copy" selected>', page)
        self.assertIn("stmt-btn-followup is-set", page)
        self.assertIn('<option value="">Clear follow-up</option>', page)
        self.assertNotIn("by erin@vive.com", page)
        # Separate from Completed.
        self.assertIsNone(completion.marked("S1"))

        self.client.post("/exceptions/Douglas%20Infiniti/status", data={"statement_id": "S1", "status": ""})
        self.assertIsNone(completion.current_status("S1"))
        self.assertNotIn("stmt-btn-followup is-set", self._page())

    def test_unknown_status_is_refused(self):
        resp = self.client.post("/exceptions/Douglas%20Infiniti/status",
                                data={"statement_id": "S1", "status": "paid"}, follow_redirects=False)
        self.assertIn("unknown+follow-up", resp.headers["location"])
        self.assertEqual(completion.all_statuses(), {})


class TestStatusLog(_SqliteTable):

    def test_newest_pick_wins_and_every_pick_is_kept(self):
        completion.set_status("S1", "requested_copy", "erin@vive.com")
        completion.set_status("S1", "waiting_to_post", "jenn@vive.com")
        completion.set_status("S2", "sent_to_shop", "erin@vive.com")
        completion.set_status("S2", "", "erin@vive.com")
        now = completion.all_statuses()
        self.assertEqual(set(now), {"S1"})
        self.assertEqual((now["S1"]["label"], now["S1"]["set_by"]), ("Waiting to post", "jenn@vive.com"))
        self.assertEqual(len(self.db.execute("SELECT * FROM statement_status_log").fetchall()), 4)
        with self.assertRaises(ValueError):
            completion.set_status("S1", "bogus", "erin@vive.com")


if __name__ == "__main__":
    unittest.main()
