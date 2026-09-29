"""
tests/test_home_time_window.py

Home's time filter: web/time_window.py's Eastern-day/month -> UTC
boundaries (both DST transitions), the "Last run" session grouping, the
labels; queries.get_home_dashboard()'s one runs-in-window query driving
the KPI cards, "N of M" and the table together; and the route's URL
handling (defaults, fallbacks, and which params each link keeps).

Query tests run the real SQL against in-memory SQLite stand-ins for the
Fabric Warehouse and Azure SQL (same approach as
tests/test_list_filters_and_sort.py). Timestamps are stored in the same
"YYYY-MM-DD HH:MM:SS[.ffffff]" text form the adapter below binds window
boundaries in, so SQLite's text comparison orders them correctly -- on
Fabric they are real DATETIME2 values and bound datetimes.
"""

import os
import re
import sqlite3
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from web import queries
from web import time_window as tw
from web.deps import require_login
from web.routers import dashboard

sqlite3.register_adapter(datetime, lambda d: d.isoformat(" "))

U = lambda *a: datetime(*a)  # naive UTC, as pyodbc returns DATETIME2


# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------

class TestEasternBoundaries(unittest.TestCase):

    def test_edt_day_starts_at_0400_utc(self):
        self.assertEqual(tw.day_bounds(date(2026, 9, 29)), (U(2026, 9, 29, 4), U(2026, 9, 30, 4)))

    def test_est_day_starts_at_0500_utc(self):
        self.assertEqual(tw.day_bounds(date(2026, 12, 15)), (U(2026, 12, 15, 5), U(2026, 12, 16, 5)))

    def test_spring_forward_day_is_23_hours(self):
        start, end = tw.day_bounds(date(2026, 3, 8))
        self.assertEqual((start, end), (U(2026, 3, 8, 5), U(2026, 3, 9, 4)))
        self.assertEqual(end - start, timedelta(hours=23))

    def test_fall_back_day_is_25_hours(self):
        start, end = tw.day_bounds(date(2026, 11, 1))
        self.assertEqual((start, end), (U(2026, 11, 1, 4), U(2026, 11, 2, 5)))
        self.assertEqual(end - start, timedelta(hours=25))

    def test_month_spanning_fall_back(self):
        self.assertEqual(tw.month_bounds(2026, 11), (U(2026, 11, 1, 4), U(2026, 12, 1, 5)))

    def test_month_spanning_spring_forward(self):
        self.assertEqual(tw.month_bounds(2026, 3), (U(2026, 3, 1, 5), U(2026, 4, 1, 4)))

    def test_december_rolls_into_january(self):
        self.assertEqual(tw.month_bounds(2026, 12), (U(2026, 12, 1, 5), U(2027, 1, 1, 5)))

    def test_run_just_before_eastern_midnight_belongs_to_previous_day(self):
        sep28 = tw.resolve_window("date", "2026-09-28")
        sep29 = tw.resolve_window("date", "2026-09-29")
        late = U(2026, 9, 29, 3, 59, 59)   # 11:59:59 PM ET, Sep 28
        midnight = U(2026, 9, 29, 4)       # 12:00 AM ET, Sep 29
        self.assertTrue(sep28.start_utc <= late < sep28.end_utc)
        self.assertFalse(sep29.start_utc <= late < sep29.end_utc)
        self.assertTrue(sep29.start_utc <= midnight < sep29.end_utc)
        self.assertFalse(sep28.start_utc <= midnight < sep28.end_utc)


class TestResolveWindow(unittest.TestCase):

    NOW = datetime(2026, 9, 29, 13, 0, tzinfo=timezone.utc)  # 9:00 AM ET

    def test_default_is_last_run(self):
        w = tw.resolve_window(timestamps=[U(2026, 9, 29, 12)], now=self.NOW)
        self.assertEqual(w.range, "last")

    def test_date_alone_implies_range_date(self):
        w = tw.resolve_window(None, "2026-09-28", None)
        self.assertEqual((w.range, w.date, w.start_utc), ("date", "2026-09-28", U(2026, 9, 28, 4)))

    def test_month_alone_implies_range_month(self):
        w = tw.resolve_window(None, None, "2026-11")
        self.assertEqual((w.range, w.month, w.start_utc, w.end_utc),
                         ("month", "2026-11", U(2026, 11, 1, 4), U(2026, 12, 1, 5)))

    def test_bad_values_fall_back_to_last(self):
        for args in (("date", "2026-13-40", None), ("date", "", None), ("month", None, "2026-9x"),
                     ("month", None, None), ("bogus", None, None), (None, "not-a-date", None)):
            with self.subTest(args=args):
                self.assertEqual(tw.resolve_window(*args, timestamps=[U(2026, 9, 29)]).range, "last")

    def test_today_uses_the_eastern_calendar_day(self):
        # 02:00Z on Sep 29 is still 10 PM on Sep 28 in New York.
        w = tw.resolve_window("today", now=datetime(2026, 9, 29, 2, 0, tzinfo=timezone.utc))
        self.assertEqual((w.date, w.start_utc, w.end_utc), ("2026-09-28", U(2026, 9, 28, 4), U(2026, 9, 29, 4)))

    def test_this_month_uses_the_eastern_calendar_month(self):
        w = tw.resolve_window("month_current", now=datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc))
        self.assertEqual((w.month, w.start_utc, w.end_utc), ("2026-09", U(2026, 9, 1, 4), U(2026, 10, 1, 4)))

    def test_all_time_has_no_bounds(self):
        w = tw.resolve_window("all")
        self.assertEqual(w.sql(), ("", []))

    def test_sql_is_a_bound_half_open_predicate(self):
        w = tw.resolve_window("date", "2026-09-28")
        self.assertEqual(w.sql(), (" AND reconciliation_timestamp >= ? AND reconciliation_timestamp < ?",
                                   [U(2026, 9, 28, 4), U(2026, 9, 29, 4)]))


class TestLastRunSession(unittest.TestCase):

    def test_chains_back_while_gaps_are_within_two_hours(self):
        ts = [U(2026, 9, 29, 12, 8), U(2026, 9, 29, 11, 0), U(2026, 9, 29, 9, 30), U(2026, 9, 29, 7, 36),
              U(2026, 9, 28, 9, 31)]  # last gap ~22h breaks the chain
        self.assertEqual(tw.last_run_bounds(ts), (U(2026, 9, 29, 7, 36), U(2026, 9, 29, 12, 8)))

    def test_a_gap_over_two_hours_starts_a_new_session(self):
        ts = [U(2026, 9, 29, 12, 8), U(2026, 9, 29, 7, 36)]  # 4h32m apart
        self.assertEqual(tw.last_run_bounds(ts), (U(2026, 9, 29, 12, 8), U(2026, 9, 29, 12, 8)))

    def test_gap_of_exactly_two_hours_still_chains(self):
        ts = [U(2026, 9, 29, 12), U(2026, 9, 29, 10)]
        self.assertEqual(tw.last_run_bounds(ts), (U(2026, 9, 29, 10), U(2026, 9, 29, 12)))

    def test_gap_just_over_two_hours_breaks(self):
        ts = [U(2026, 9, 29, 12), U(2026, 9, 29, 9, 59, 59)]
        self.assertEqual(tw.last_run_bounds(ts), (U(2026, 9, 29, 12), U(2026, 9, 29, 12)))

    def test_order_and_input_types_do_not_matter(self):
        ts = ["2026-09-29T10:30:00+00:00", U(2026, 9, 29, 12), "2026-09-29 11:15:00"]
        self.assertEqual(tw.last_run_bounds(ts), (U(2026, 9, 29, 10, 30), U(2026, 9, 29, 12)))

    def test_threshold_is_the_named_constant(self):
        self.assertEqual(tw.LAST_RUN_GAP, timedelta(hours=2))

    def test_single_run(self):
        w = tw.resolve_window("last", timestamps=[U(2026, 9, 29, 12, 8)])
        self.assertEqual(w.start_utc, U(2026, 9, 29, 12, 8))
        self.assertGreater(w.end_utc, U(2026, 9, 29, 12, 8))  # latest run is included

    def test_no_runs_gives_an_empty_window(self):
        w = tw.resolve_window("last", timestamps=[])
        self.assertTrue(w.empty)
        self.assertEqual(w.sql(), (" AND 1 = 0", []))


class TestMonthOptionsAndLabels(unittest.TestCase):

    def test_month_options_are_eastern_months_with_runs_newest_first(self):
        ts = [U(2026, 10, 1, 2), U(2026, 9, 15), U(2026, 8, 3), U(2026, 9, 1)]  # Oct 1 02:00Z = Sep 30 ET
        self.assertEqual(tw.month_options(ts), ["2026-09", "2026-08"])

    def test_last_run_label_same_day(self):
        w = tw.resolve_window("last", timestamps=[U(2026, 9, 29, 7, 36), U(2026, 9, 29, 9, 30),
                                                  U(2026, 9, 29, 11, 0), U(2026, 9, 29, 12, 8)])
        self.assertEqual(tw.window_label(w, 47), "Last run · Sep 29, 3:36 AM – 8:08 AM ET · 47 statements")

    def test_last_run_label_single_run(self):
        w = tw.resolve_window("last", timestamps=[U(2026, 9, 29, 12, 8)])
        self.assertEqual(tw.window_label(w, 1), "Last run · Sep 29, 8:08 AM ET · 1 statement")

    def test_last_run_label_across_midnight(self):
        w = tw.resolve_window("last", timestamps=[U(2026, 9, 29, 3, 30), U(2026, 9, 29, 5, 10)])
        self.assertEqual(tw.window_title(w), "Last run · Sep 28, 11:30 PM – Sep 29, 1:10 AM ET")

    def test_other_labels(self):
        now = datetime(2026, 9, 29, 13, tzinfo=timezone.utc)
        self.assertEqual(tw.window_label(tw.resolve_window("today", now=now), 0), "Today · Sep 29 · no runs yet")
        self.assertEqual(tw.window_label(tw.resolve_window("month_current", now=now), 213),
                         "This month · September 2026 · 213 statements")
        self.assertEqual(tw.window_label(tw.resolve_window("date", "2026-09-28"), 53), "Sep 28, 2026 · 53 statements")
        self.assertEqual(tw.window_label(tw.resolve_window("month", None, "2026-08"), 0), "August 2026 · no runs")
        self.assertEqual(tw.window_label(tw.resolve_window("all"), 1500), "All time · 1,500 statements")

    def test_short_labels_and_empty_messages(self):
        self.assertEqual(tw.window_short(tw.resolve_window("date", "2026-09-28")), "Sep 28, 2026")
        self.assertEqual(tw.window_short(tw.resolve_window("all")), "all time")
        self.assertEqual(tw.empty_message(tw.resolve_window("today")), "No reconciliation runs today yet.")
        self.assertEqual(tw.empty_message(tw.resolve_window("month", None, "2026-08")),
                         "No reconciliation runs in August 2026.")


# ---------------------------------------------------------------------------
# get_home_dashboard() -- one query drives cards + N of M + table
# ---------------------------------------------------------------------------

_SELECT_TOP_RE = re.compile(r"^\s*SELECT\s+TOP\s+(\d+)\s+(.*)$", re.IGNORECASE | re.DOTALL)


def _query_fn(conn):
    def query(sql, params=None):
        top = _SELECT_TOP_RE.match(sql)
        if top:
            sql = f"SELECT {top.group(2)}\nLIMIT {top.group(1)}"
        return [dict(r) for r in conn.execute(sql, params or []).fetchall()]
    return query


class TestHomeDashboardQuery(unittest.TestCase):

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
        self.local = sqlite3.connect(":memory:", check_same_thread=False)
        self.local.row_factory = sqlite3.Row
        self.local.execute("CREATE TABLE document_intake_log (statement_id TEXT, statement_period TEXT, shop_or_entity TEXT)")
        self.local.execute("CREATE TABLE jobs (job_id TEXT, statement_id TEXT, submitted_at TEXT)")
        for target, conn in (("web.queries.recon_query", self.fabric), ("web.queries.execute_query", self.local)):
            patcher = mock.patch(target, _query_fn(conn))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.fabric.close)
        self.addCleanup(self.local.close)

        # Session A (Sep 29 ET): three runs, each gap under 2h.
        self._run("A1", "Fenix", ts="2026-09-29 12:08:00.421634", invoices=10, matched=10, exc=0, total=100, period="2026-08")
        self._run("A2", "Bald Hill", ts="2026-09-29 11:00:00", invoices=20, matched=15, exc=5, total=200, period="2026-08")
        self._run("A3", "Fenix", ts="2026-09-29 09:30:16", invoices=5, matched=4, exc=1, total=50, period="2026-07")
        # Session B (Sep 28 ET), >2h before A.
        self._run("B1", "Abc Parts", ts="2026-09-28 09:31:00", invoices=40, matched=40, exc=0, total=400, period="2026-08")
        # Sep 28 23:59:59 ET (03:59:59Z Sep 29) -- belongs to Sep 28, not Sep 29.
        self._run("B2", "Abc Parts", ts="2026-09-29 03:59:59", invoices=1, matched=1, exc=0, total=1, period="2026-08")

    def _run(self, sid, vendor, *, ts, invoices, matched, exc, total, period=None):
        self.fabric.execute(
            "INSERT INTO silver.recon_summary VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, 1)",
            [sid, vendor, invoices, matched, exc, total, "RECONCILED" if exc == 0 else "EXCEPTIONS_PRESENT", ts],
        )
        if period:
            self.local.execute("INSERT INTO document_intake_log VALUES (?, ?, NULL)", [sid, period])

    def _window(self, *args, **kwargs):
        return tw.resolve_window(*args, timestamps=queries.get_run_timestamps(), **kwargs)

    def _ids(self, data):
        return [r["statement_id"] for r in data["runs"]]

    def test_last_run_covers_only_the_latest_session(self):
        data = queries.get_home_dashboard(self._window())
        self.assertEqual(self._ids(data), ["A1", "A2", "A3"])
        self.assertEqual(data["statement_count"], 3)

    def test_cards_table_and_n_of_m_cover_the_same_runs(self):
        data = queries.get_home_dashboard(self._window())
        k = data["kpis"]
        self.assertEqual((k["total_invoices"], k["auto_reconciled"], k["statement_total"], k["vendor_count"]),
                         (35, 29, 350.0, 2))
        self.assertEqual(k["match_rate"], round(29 / 35 * 100, 1))
        # Open exceptions = SUM(exception_count) of the same rows as the table.
        self.assertEqual(k["open_exceptions"], sum(r["exception_count"] for r in data["runs"]))
        self.assertEqual(k["open_exceptions"], 6)
        self.assertEqual((data["reconciled"], data["total"]), (1, 3))

    def test_status_and_period_narrow_the_table_but_not_the_cards(self):
        base = queries.get_home_dashboard(self._window())
        data = queries.get_home_dashboard(self._window(), status="exceptions", period="2026-08")
        self.assertEqual(self._ids(data), ["A2"])
        self.assertEqual((data["reconciled"], data["total"]), (0, 1))
        self.assertEqual(data["kpis"], base["kpis"])
        self.assertEqual(data["statement_count"], 3)

    def test_period_options_come_from_the_window_only(self):
        data = queries.get_home_dashboard(self._window("date", "2026-09-28"))
        self.assertEqual(self._ids(data), ["B2", "B1"])
        self.assertEqual(data["period_options"], ["2026-08"])

    def test_eastern_day_boundary_in_sql(self):
        sep29 = queries.get_home_dashboard(self._window("date", "2026-09-29"))
        self.assertEqual(self._ids(sep29), ["A1", "A2", "A3"])  # B2 (11:59:59 PM ET Sep 28) excluded

    def test_month_window(self):
        data = queries.get_home_dashboard(self._window("month", None, "2026-09"))
        self.assertEqual(data["statement_count"], 5)
        self.assertEqual(queries.get_home_dashboard(self._window("month", None, "2026-08"))["statement_count"], 0)

    def test_all_time_matches_every_run(self):
        self.assertEqual(queries.get_home_dashboard(self._window("all"))["statement_count"], 5)
        self.assertEqual(queries.get_home_dashboard(None)["statement_count"], 5)

    def test_empty_window_is_all_zeros_not_an_error(self):
        data = queries.get_home_dashboard(self._window("date", "2026-01-01"))
        self.assertEqual(data["runs"], [])
        self.assertEqual((data["total"], data["reconciled"], data["statement_count"]), (0, 0, 0))
        self.assertEqual(data["kpis"], {"total_invoices": 0, "auto_reconciled": 0, "open_exceptions": 0,
                                        "statement_total": 0, "vendor_count": 0, "match_rate": None})

    def test_no_runs_at_all(self):
        self.fabric.execute("DELETE FROM silver.recon_summary")
        w = self._window()
        self.assertTrue(w.empty)
        self.assertEqual(queries.get_home_dashboard(w)["statement_count"], 0)

    def test_month_options_from_run_timestamps(self):
        self.assertEqual(tw.month_options(queries.get_run_timestamps()), ["2026-09"])


# ---------------------------------------------------------------------------
# Route -- URL params and what every link keeps
# ---------------------------------------------------------------------------

class TestHomeRouteTimeWindow(unittest.TestCase):

    def setUp(self):
        self.windows = []
        self.result = {
            "kpis": {"total_invoices": 599, "auto_reconciled": 512, "open_exceptions": 87,
                     "statement_total": 1234.5, "vendor_count": 5, "match_rate": 85.5},
            "runs": [{"statement_id": "S1", "vendor_name": "Fenix", "vendor_display_name": "Fenix", "shop": None,
                      "statement_period": "2026-08", "total_invoice_count": 5, "matched_count": 5,
                      "exception_count": 0, "overall_status": "RECONCILED", "reconciliation_timestamp": None,
                      "job_id": None}],
            "total": 47, "reconciled": 19, "period_options": ["2026-08"], "statement_count": 47,
        }

        def get_home_dashboard(window=None, status="all", period=None, limit=10):
            self.windows.append((window, status, period))
            return self.result

        fns = {
            "get_run_timestamps": lambda: [U(2026, 9, 29, 7, 36), U(2026, 9, 29, 9, 30), U(2026, 9, 29, 11, 0),
                                           U(2026, 9, 29, 12, 8), U(2026, 8, 20, 12)],
            "get_home_dashboard": get_home_dashboard,
            "get_active_jobs": lambda: [], "get_failed_jobs": lambda: [],
            "get_recent_completed_batches": lambda limit=3: [],
            "get_last_netsuite_sync": lambda: None, "get_last_outlook_sync": lambda: None,
            "get_open_recon_exceptions_count": lambda: 1806, "get_pending_review_count": lambda: 3,
        }
        for name, fn in fns.items():
            patcher = mock.patch(f"web.queries.{name}", fn)
            patcher.start()
            self.addCleanup(patcher.stop)
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret")
        app.include_router(dashboard.router)
        app.dependency_overrides[require_login] = lambda: "tester"
        self.client = TestClient(app)

    def _get(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return resp.text.replace("&amp;", "&")

    def _window(self):
        return self.windows[-1][0]

    def test_default_is_last_run_with_label(self):
        html = self._get("/")
        self.assertEqual(self._window().range, "last")
        self.assertIn("Last run · Sep 29, 3:36 AM – 8:08 AM ET · 47 statements", html)
        self.assertIn('href="/" class="filter-chip active">Last run', html)

    def test_cards_use_the_window_sub_labels(self):
        html = self._get("/")
        self.assertIn("across 5 vendors · last run", html)
        self.assertIn("85.5% matched · last run", html)
        self.assertIn("needs review · last run", html)
        self.assertIn("19 of 47 statements reconciled", html)

    def test_date_alone_selects_that_day(self):
        html = self._get("/?date=2026-09-28")
        self.assertEqual((self._window().range, self._window().date), ("date", "2026-09-28"))
        self.assertIn('value="2026-09-28"', html)
        self.assertRegex(html, r'id="window-date" class="filter-chip active"')

    def test_month_alone_selects_that_month_and_options_have_runs_only(self):
        html = self._get("/?month=2026-09")
        self.assertEqual((self._window().range, self._window().month), ("month", "2026-09"))
        options = re.search(r'<select name="month".*?</select>', html, re.S).group(0)
        self.assertEqual(re.findall(r'<option value="([^"]*)"', options), ["", "2026-09", "2026-08"])
        self.assertIn('<option value="2026-09" selected>Sep 2026</option>', options)

    def test_bad_params_fall_back_to_last_run(self):
        for url in ("/?range=bogus", "/?range=date&date=nope", "/?month=2026-99", "/?date=2026-02-30"):
            with self.subTest(url=url):
                self._get(url)
                self.assertEqual(self._window().range, "last")

    def test_range_chips_keep_status_and_clear_period(self):
        html = self._get("/?range=date&date=2026-09-28&status=exceptions&period=2026-08")
        self.assertIn('href="/?status=exceptions" class="filter-chip ">Last run', html)
        self.assertIn('href="/?range=today&status=exceptions" class="filter-chip ">Today', html)
        self.assertIn('href="/?range=month_current&status=exceptions" class="filter-chip ">This month', html)
        self.assertIn('href="/?range=all&status=exceptions" class="filter-chip ">All time', html)

    def test_date_and_month_forms_keep_status_not_period(self):
        html = self._get("/?range=all&status=reconciled&period=2026-08")
        for form in re.findall(r'<form method="get" action="/" style="display:contents">.*?</form>', html, re.S):
            self.assertIn('<input type="hidden" name="status" value="reconciled">', form)
            self.assertNotIn('name="period"', form)

    def test_status_chips_and_period_select_keep_the_window(self):
        html = self._get("/?range=date&date=2026-09-28&status=exceptions&period=2026-08")
        self.assertIn('href="/?range=date&date=2026-09-28&period=2026-08" class="filter-chip ">All', html)
        self.assertIn('href="/?range=date&date=2026-09-28&status=reconciled&period=2026-08" class="filter-chip ">Reconciled', html)
        runs_form = re.search(r'<form method="get" action="/" class="filter-chips"[^>]*id="runs-filters">.*?</form>', html, re.S).group(0)
        self.assertIn('<input type="hidden" name="range" value="date">', runs_form)
        self.assertIn('<input type="hidden" name="date" value="2026-09-28">', runs_form)
        self.assertIn('<input type="hidden" name="status" value="exceptions">', runs_form)

    def test_status_period_passed_through_with_window(self):
        self._get("/?range=month&month=2026-09&status=exceptions&period=2026-08")
        window, status, period = self.windows[-1]
        self.assertEqual((window.range, window.month, status, period), ("month", "2026-09", "exceptions", "2026-08"))

    def test_selected_period_missing_from_window_stays_selected(self):
        html = self._get("/?period=2026-01")
        self.assertIn('<option value="2026-01" selected>Jan 2026</option>', html)

    def test_empty_window_message_links_to_last_run_and_all_time(self):
        self.result = {**self.result, "runs": [], "total": 0, "reconciled": 0, "statement_count": 0,
                       "period_options": [],
                       "kpis": {"total_invoices": 0, "auto_reconciled": 0, "open_exceptions": 0,
                                "statement_total": 0, "vendor_count": 0, "match_rate": None}}
        html = self._get("/?range=today&status=exceptions")
        self.assertIn("No reconciliation runs today yet.", html)
        self.assertIn('<a href="/?status=exceptions" class="link">Last run</a>', html)
        self.assertIn('<a href="/?range=all&status=exceptions" class="link">All time</a>', html)
        self.assertIn("—% matched · today", html)
        self.assertIn("none open · today", html)
        self.assertRegex(html, r"Today · \w{3} \d{1,2} · no runs yet")

    def test_filtered_out_window_offers_clear_filters_that_keeps_the_window(self):
        self.result = {**self.result, "runs": [], "total": 0, "reconciled": 0}
        html = self._get("/?range=date&date=2026-09-28&status=exceptions&period=2026-07")
        self.assertIn('No reconciliation runs match these filters. <a href="/?range=date&date=2026-09-28" class="link">Clear filters</a>', html)

    def test_pending_review_line_is_not_window_scoped(self):
        html = self._get("/?range=date&date=2026-01-01")
        self.assertIn("3 rows pending review", html)


if __name__ == "__main__":
    unittest.main()
