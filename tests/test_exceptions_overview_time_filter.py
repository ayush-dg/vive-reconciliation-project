"""
tests/test_exceptions_overview_time_filter.py

The Exceptions overview's time filter (2026-09-30): the same controls and
web/time_window.py definitions as Home, but defaulting to "all" (not
"last"), and exceptions-only vendors (no recon_summary row, so no run
timestamp or statement_id at all) always shown and always counted,
regardless of the selected window.

Query-level tests run the real SQL against in-memory SQLite stand-ins for
the Fabric Warehouse and Azure SQL (same approach as
tests/test_home_time_window.py). Route-level tests patch every
web.queries call the route makes.
"""

import os
import re
import sqlite3
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from web import queries
from web import time_window as tw
from web.deps import require_login
from web.routers import exceptions

sqlite3.register_adapter(datetime, lambda d: d.isoformat(" "))

U = lambda *a: datetime(*a)  # naive UTC, as pyodbc returns DATETIME2


def _job(statement_id, submitted_at, status="COMPLETED"):
    return {"statement_id": statement_id, "submitted_at": submitted_at, "status": status}


_SELECT_TOP_RE = re.compile(r"^\s*SELECT\s+TOP\s+(\d+)\s+(.*)$", re.IGNORECASE | re.DOTALL)


def _query_fn(conn):
    def query(sql, params=None):
        top = _SELECT_TOP_RE.match(sql)
        if top:
            sql = f"SELECT {top.group(2)}\nLIMIT {top.group(1)}"
        return [dict(r) for r in conn.execute(sql, params or []).fetchall()]
    return query


class TestGetExceptionRunsWindow(unittest.TestCase):

    def setUp(self):
        self.fabric = sqlite3.connect(":memory:", check_same_thread=False)
        self.fabric.row_factory = sqlite3.Row
        self.fabric.execute("ATTACH DATABASE ':memory:' AS silver")
        self.fabric.execute(
            """CREATE TABLE silver.recon_summary (
                   statement_id TEXT, vendor_name TEXT, statement_period TEXT,
                   total_invoice_count INTEGER, matched_count INTEGER, exception_count INTEGER,
                   statement_total REAL, overall_status TEXT, reconciliation_timestamp TEXT,
                   is_latest_version INTEGER)"""
        )
        self.fabric.execute(
            """CREATE TABLE silver.recon_exceptions (
                   exception_id TEXT, statement_id TEXT, source_file TEXT, vendor_id TEXT,
                   shop TEXT, exception_reason TEXT, exception_status TEXT, date_raised TEXT)"""
        )
        self.local = sqlite3.connect(":memory:", check_same_thread=False)
        self.local.row_factory = sqlite3.Row
        self.local.execute("CREATE TABLE document_intake_log (statement_id TEXT, billing_location TEXT, statement_period TEXT, shop_or_entity TEXT)")
        self.local.execute("CREATE TABLE jobs (job_id TEXT, statement_id TEXT, submitted_at TEXT, source_blob_path TEXT, "
                           "status TEXT DEFAULT 'COMPLETED')")
        for target, conn in (("web.queries.recon_query", self.fabric), ("web.queries.execute_query", self.local)):
            patcher = mock.patch(target, _query_fn(conn))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.fabric.close)
        self.addCleanup(self.local.close)

        self._run("A1", "Fenix", ts="2026-09-29 12:08:00", exc=2)
        self._run("A2", "Bald Hill", ts="2026-09-29 12:04:00", exc=0)
        self._run("B1", "Abc Parts", ts="2026-09-20 09:31:00", exc=1)
        # Exceptions-only: no recon_summary row at all for this source_file.
        self._orphan_exception("orphan.pdf", "Vendor Not Resolved in NetSuite", n=3)

    def _run(self, sid, vendor, *, ts, exc, invoices=10, matched=8, total=100.0, period="2026-08"):
        self.fabric.execute(
            "INSERT INTO silver.recon_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
            [sid, vendor, period, invoices, matched, exc, total,
             "RECONCILED" if exc == 0 else "EXCEPTIONS_PRESENT", ts],
        )
        for i in range(exc):
            self.fabric.execute(
                "INSERT INTO silver.recon_exceptions VALUES (?, ?, NULL, NULL, NULL, ?, 'OPEN', ?)",
                [f"{sid}-e{i}", sid, "Not Found in NetSuite", ts],
            )

    def _orphan_exception(self, source_file, reason, n=1):
        for i in range(n):
            self.fabric.execute(
                "INSERT INTO silver.recon_exceptions VALUES (?, NULL, ?, NULL, NULL, ?, 'OPEN', ?)",
                [f"{source_file}-e{i}", source_file, reason, "2026-09-15 00:00:00"],
            )

    def _window(self, *args, **kwargs):
        return tw.resolve_window(*args, timestamps=queries.get_run_timestamps(),
                                 outlook_jobs=queries.get_outlook_synced_jobs(), **kwargs)

    def _ids(self, runs):
        return {r["statement_id"] for r in runs if r.get("statement_id")}

    def test_no_window_returns_every_run_plus_exceptions_only(self):
        runs = queries.get_exception_runs()
        self.assertEqual(self._ids(runs), {"A1", "A2", "B1"})
        self.assertEqual(sum(1 for r in runs if r.get("exceptions_only")), 1)

    def test_calendar_window_scopes_summary_backed_runs(self):
        runs = queries.get_exception_runs(self._window("date", "2026-09-29"))
        self.assertEqual(self._ids(runs), {"A1", "A2"})

    def test_exceptions_only_vendor_always_present_regardless_of_window(self):
        for window in (self._window("date", "2026-09-29"), self._window("date", "2026-01-01"),
                      self._window("last"), self._window("all")):
            with self.subTest(window=window.range):
                runs = queries.get_exception_runs(window)
                orphans = [r for r in runs if r.get("exceptions_only")]
                self.assertEqual(len(orphans), 1)
                self.assertEqual(orphans[0]["exception_count"], 3)

    def test_last_run_scopes_by_outlook_statement_ids(self):
        self.local.execute("INSERT INTO jobs (statement_id, submitted_at, source_blob_path) VALUES (?, ?, ?)",
                           ["A1", "2026-09-29 12:08:00", "mailbox/x.pdf"])
        self.local.execute("INSERT INTO jobs (statement_id, submitted_at, source_blob_path) VALUES (?, ?, ?)",
                           ["A2", "2026-09-29 12:05:00", "mailbox/y.pdf"])
        # B1 is NOT part of this sync (much older submitted_at).
        self.local.execute("INSERT INTO jobs (statement_id, submitted_at, source_blob_path) VALUES (?, ?, ?)",
                           ["B1", "2026-09-01 00:00:00", "mailbox/z.pdf"])
        runs = queries.get_exception_runs(self._window("last"))
        self.assertEqual(self._ids(runs), {"A1", "A2"})
        # Exceptions-only still there.
        self.assertEqual(sum(1 for r in runs if r.get("exceptions_only")), 1)

    def test_empty_window_still_shows_exceptions_only_vendor(self):
        runs = queries.get_exception_runs(self._window("date", "2026-01-01"))
        self.assertEqual(self._ids(runs), set())
        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0]["exceptions_only"])

    def test_no_window_matches_old_unwindowed_call_shape(self):
        """window=None must behave exactly like the pre-window function."""
        with_none = queries.get_exception_runs(None)
        no_arg = queries.get_exception_runs()
        self.assertEqual(self._ids(with_none), self._ids(no_arg))


# ---------------------------------------------------------------------------
# Route -- default, chips, URL params, empty state
# ---------------------------------------------------------------------------

def _client():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(exceptions.router)
    app.dependency_overrides[require_login] = lambda: "tester"
    return TestClient(app)


class TestExceptionsOverviewRoute(unittest.TestCase):

    def setUp(self):
        self.windows = []
        self.run_row = {
            "statement_id": "S1", "vendor_name": "Fenix", "vendor_display_name": "Fenix",
            "shop": None, "billing_location": None, "statement_period": "2026-08",
            "total_invoice_count": 10, "matched_count": 8, "exception_count": 2,
            "statement_total": 100.0, "overall_status": "EXCEPTIONS_PRESENT",
            "reconciliation_timestamp": None, "reason_breakdown": {"not found in NetSuite": 2},
            "aging": None, "url_name": "Fenix",
        }
        self.orphan_row = {
            "statement_id": None, "source_file": "orphan.pdf", "vendor_name": "Orphan Co",
            "vendor_display_name": "Orphan Co", "shop": None, "billing_location": None,
            "statement_period": None, "total_invoice_count": 0, "matched_count": 0,
            "exception_count": 3, "statement_total": 0, "overall_status": "EXCEPTIONS_PRESENT",
            "reconciliation_timestamp": None, "reason_breakdown": {"vendor not resolved": 3},
            "aging": None, "exceptions_only": True, "url_name": "Orphan%20Co",
        }
        self.runs = [dict(self.run_row), dict(self.orphan_row)]

        def get_exception_runs(window=None):
            self.windows.append(window)
            return [dict(r) for r in self.runs]

        fns = {
            "get_exception_runs": get_exception_runs,
            "get_run_timestamps": lambda: [U(2026, 9, 29, 12)],
            "get_outlook_synced_jobs": lambda: [_job("S1", U(2026, 9, 29, 12, 8))],
            "get_open_recon_exceptions_count": lambda: 0,
            "get_pending_review_count": lambda: 0,
        }
        for name, fn in fns.items():
            patcher = mock.patch(f"web.queries.{name}", fn)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = _client()

    def _get(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return resp.text.replace("&amp;", "&")

    def _window(self):
        return self.windows[-1]

    def test_default_is_last_run(self):
        """Same default as Home's since 2026-10-01 (was "all")."""
        self._get("/exceptions")
        self.assertEqual(self._window().range, "last")

    def test_header_counts_both_the_run_and_the_exceptions_only_vendor(self):
        html = self._get("/exceptions")
        self.assertIn("5 open across 2 vendors", html)

    def test_only_last_run_and_today_are_chips(self):
        html = self._get("/exceptions")
        time_window = re.search(r'id="time-window".*?</div>', html, re.S).group(0)
        chip_labels = re.findall(r'class="filter-chip[^"]*">([^<]+)</a>', time_window)
        self.assertEqual(chip_labels, ["Today", "Last run"])

    def test_no_month_select_or_all_time_option(self):
        # Removed 2026-10-01 -- the Month select's blank "All time" option
        # used to be selected by default here. An old bookmarked
        # ?range=all link still resolves; it just has no control.
        html = self._get("/exceptions")
        self.assertNotIn('id="window-month"', html)
        self.assertNotIn(">All time</option>", html)
        self._get("/exceptions?range=all")
        self.assertEqual(self._window().range, "all")

    def test_date_alone_selects_that_day(self):
        self._get("/exceptions?date=2026-09-28")
        self.assertEqual((self._window().range, self._window().date), ("date", "2026-09-28"))

    def test_month_alone_selects_that_month(self):
        self._get("/exceptions?month=2026-09")
        self.assertEqual((self._window().range, self._window().month), ("month", "2026-09"))

    def test_unknown_range_falls_back_to_last(self):
        """Same fallback as Home's since 2026-10-01 (was "all")."""
        self._get("/exceptions?range=bogus")
        self.assertEqual(self._window().range, "last")

    def test_no_outlook_syncs_yet_defaults_to_all_time(self):
        # Found on dev 2026-10-01: with no Outlook syncs at all, the "last"
        # default is an empty window, so a plain page load falls back to
        # "all" (the full backlog) instead. An unrecognised range lands on
        # the same default; an explicit ?range=last is still honoured.
        with mock.patch("web.queries.get_outlook_synced_jobs", lambda: []):
            self._get("/exceptions")
            self.assertEqual(self._window().range, "all")
            self._get("/exceptions?range=bogus")
            self.assertEqual(self._window().range, "all")
            self._get("/exceptions?range=last")
            self.assertEqual(self._window().range, "last")

    def test_last_run_reachable_via_the_chip(self):
        html = self._get("/exceptions?range=last")
        self.assertEqual(self._window().range, "last")
        # "last" is this page's own default too since 2026-10-01, so (like
        # Home's) its "Last run" chip link leaves range= out entirely.
        self.assertIn('href="/exceptions" class="filter-chip active">Last run', html)

    def test_calendar_button_and_hidden_date_input(self):
        html = self._get("/exceptions?date=2026-09-28")
        self.assertIn('id="window-date-btn"', html)
        self.assertIn('<use href="#i-calendar"/>', html)
        self.assertIn('id="window-date" class="ns-sr-only"', html)

    def test_empty_window_message_links_to_last_run(self):
        self.runs = [dict(self.orphan_row)]  # no summary-backed run in this window
        html = self._get("/exceptions?range=today")
        self.assertIn("No reconciliation runs today yet.", html)
        # "last" is this page's own default, so its URL omits range=.
        self.assertIn('href="/exceptions" class="link">Last run</a>', html)
        # No "All time" link since 2026-10-01 (the All time option is gone).
        self.assertNotIn('class="link">All time</a>', html)

    def test_sync_label_counts_jobs_by_status(self):
        # 2026-10-06: S1 is the only run with a recon_summary row; the
        # cache hit completed without one and one job failed. Read "1 of
        # 3 statements (2 still processing)" before -- nothing is in flight.
        jobs = [_job("S1", U(2026, 9, 29, 12, 8)), _job("CACHE-HIT", U(2026, 9, 29, 12, 6)),
                _job(None, U(2026, 9, 29, 12, 4), "FAILED")]
        with mock.patch("web.queries.get_outlook_synced_jobs", lambda: jobs):
            html = self._get("/exceptions")
        self.assertIn("Last sync · Sep 29, 8:08 AM ET · 3 statements (2 completed, 1 failed)", html)
        self.assertNotIn("still processing", html)
        self.assertNotIn("Last Outlook sync", html)

    def test_past_syncs_button_and_no_syncs_yet_wording(self):
        html = self._get("/exceptions")
        self.assertRegex(html, r'id="window-sync-btn"[^>]*>\s*Past syncs<svg')
        self.assertNotIn("Outlook sync", html)
        with mock.patch("web.queries.get_outlook_synced_jobs", lambda: []):
            html = self._get("/exceptions?range=last")
        self.assertIn("<option disabled>No syncs yet</option>", html)
        self.assertNotIn("No Outlook syncs yet", html)

    def test_vendor_shop_location_options_rebuilt_from_the_window(self):
        html = self._get("/exceptions")
        self.assertIn(">Fenix<", html)
        # smart_title() title-cases "Orphan Co" -- confirmed its own
        # existing behaviour (unrelated to this change) renders it
        # "Orphan CO", not "Orphan Co".
        self.assertIn(">Orphan CO<", html)


class TestExceptionsSyncDropdown(unittest.TestCase):
    """The "Last run" dropdown (2026-09-30) on /exceptions -- same
    mechanism as Home's own (web/routers/dashboard.py's counterpart), just
    exercised through exceptions.py/exceptions_url()."""

    def setUp(self):
        self.windows = []
        run_row = {
            "statement_id": "S1", "vendor_name": "Fenix", "vendor_display_name": "Fenix",
            "shop": None, "billing_location": None, "statement_period": "2026-08",
            "total_invoice_count": 10, "matched_count": 8, "exception_count": 2,
            "statement_total": 100.0, "overall_status": "EXCEPTIONS_PRESENT",
            "reconciliation_timestamp": None, "reason_breakdown": {"not found in NetSuite": 2},
            "aging": None, "url_name": "Fenix",
        }

        def get_exception_runs(window=None):
            self.windows.append(window)
            return [dict(run_row)]

        fns = {
            "get_exception_runs": get_exception_runs,
            "get_run_timestamps": lambda: [],
            "get_outlook_synced_jobs": lambda: [
                _job("N1", U(2026, 9, 29, 16, 2)),
                _job("O1", U(2026, 9, 28, 12, 0)),
            ],
            "get_open_recon_exceptions_count": lambda: 0,
            "get_pending_review_count": lambda: 0,
        }
        for name, fn in fns.items():
            patcher = mock.patch(f"web.queries.{name}", fn)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = _client()

    def _get(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return resp.text.replace("&amp;", "&")

    def test_dropdown_lists_both_syncs_newest_first(self):
        html = self._get("/exceptions?range=last")
        select = re.search(r'<select name="sync".*?</select>', html, re.S).group(0)
        self.assertIn("Sep 29, 12:02 PM ET · 1 statement", select)
        self.assertIn("Sep 28, 8:00 AM ET · 1 statement", select)

    def test_choosing_an_older_sync_narrows_the_window_and_url(self):
        html = self._get("/exceptions?range=last&sync=2026-09-28T12:00:00Z")
        self.assertEqual(self.windows[-1].statement_ids, frozenset({"O1"}))
        self.assertIn('href="/exceptions?range=today"', html)

    def test_default_exceptions_page_load_selects_the_newest_sync(self):
        # Exceptions' default range is "last" since 2026-10-01 (same as
        # Home's), so a plain page load pre-selects the NEWEST sync.
        html = self._get("/exceptions")
        self.assertEqual(self._window().range, "last")
        self.assertEqual(self._window().statement_ids, frozenset({"N1"}))
        select = re.search(r'<select name="sync".*?</select>', html, re.S).group(0)
        self.assertIn('<option value="2026-09-29T16:02:00Z" selected>', select)
        self.assertNotIn('value="2026-09-28T12:00:00Z" selected', select)
        # Custom picker (2026-10-01): "None" (= the Last run chip) comes
        # first but isn't selected; with no explicit ?sync=, Last run is the
        # highlighted control and the picker's button is not.
        options = re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>', select)
        self.assertEqual(options[0], ("", "None"))
        self.assertNotIn('<option value="" selected>', select)
        self.assertIn('href="/exceptions" class="filter-chip active">Last run', html)
        self.assertRegex(html, r'class="filter-chip sync-picker-btn\s*" id="window-sync-btn"')

    def _window(self):
        return self.windows[-1]


if __name__ == "__main__":
    unittest.main()
