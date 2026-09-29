"""
tests/test_list_filters_and_sort.py

Home "Reconciliation runs" status/period filters, the exceptions review
list's sort chips, and the Validation page's period filter.

Query-level tests run the real SQL in web/queries.py against in-memory
SQLite stand-ins for both backends (an ATTACHed "silver" schema for the
Fabric Warehouse, a plain database for Azure SQL's document_intake_log/
jobs) -- same approach as tests/test_web_queries.py. Route-level tests
patch every web.queries call the route makes, so none of them reaches
Fabric or Azure SQL (the reason several older route tests fail in a local
environment without FABRIC_WAREHOUSE_NAME).
"""

import os
import re
import sqlite3
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from web import queries
from web.deps import require_login, templates
from web.routers import dashboard, exceptions, validation
from web.routers.exceptions import REASON_BADGE, SEARCHABLE_REASONS, _filter_redirect_suffix


# ---------------------------------------------------------------------------
# Fake backends
# ---------------------------------------------------------------------------

_SELECT_TOP_RE = re.compile(r"^\s*SELECT\s+TOP\s+(\d+)\s+(.*)$", re.IGNORECASE | re.DOTALL)


def _make_fabric_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("ATTACH DATABASE ':memory:' AS silver")
    conn.execute(
        """
        CREATE TABLE silver.recon_summary (
            statement_id TEXT, vendor_name TEXT, statement_period TEXT,
            total_invoice_count INTEGER, matched_count INTEGER, exception_count INTEGER,
            overall_status TEXT, reconciliation_timestamp TEXT, is_latest_version INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE silver.recon_exceptions (
            exception_id TEXT, vendor_id TEXT, invoice_number TEXT, statement_amount REAL,
            erp_amount REAL, exception_reason TEXT, exception_status TEXT, statement_id TEXT,
            date_raised TEXT, escalation_status TEXT, escalated_at TEXT, source_file TEXT
        )
        """
    )
    return conn


def _make_local_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE document_intake_log (statement_id TEXT, statement_period TEXT, shop_or_entity TEXT)"
    )
    conn.execute("CREATE TABLE jobs (job_id TEXT, statement_id TEXT, submitted_at TEXT)")
    return conn


def _query_fn(conn, translate_top=False):
    def query(sql, params=None):
        if translate_top:
            top_match = _SELECT_TOP_RE.match(sql)
            if top_match:
                n, rest = top_match.groups()
                sql = f"SELECT {rest}\nLIMIT {n}"
        return [dict(r) for r in conn.execute(sql, params or []).fetchall()]
    return query


class _BackendTestCase(unittest.TestCase):
    def setUp(self):
        self.fabric = _make_fabric_db()
        self.local = _make_local_db()
        for target, fn in (
            ("web.queries.recon_query", _query_fn(self.fabric, translate_top=True)),
            ("web.queries.execute_query", _query_fn(self.local)),
        ):
            patcher = mock.patch(target, fn)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.fabric.close)
        self.addCleanup(self.local.close)

    def _run(self, statement_id, *, exception_count, ts, period=None, shop=None, is_latest=1):
        self.fabric.execute(
            "INSERT INTO silver.recon_summary VALUES (?, ?, NULL, 10, ?, ?, ?, ?, ?)",
            [statement_id, "Keystone Automotive", 10 - exception_count, exception_count,
             "RECONCILED" if exception_count == 0 else "EXCEPTIONS_PRESENT", ts, is_latest],
        )
        if period is not None or shop is not None:
            self.local.execute(
                "INSERT INTO document_intake_log VALUES (?, ?, ?)",
                [statement_id, period, f'["{shop}"]' if shop else None],
            )

    def _exc(self, exception_id, *, amount, raised, invoice, statement_id="STMT-1",
             reason="Not Found in NetSuite", source_file=None):
        self.fabric.execute(
            "INSERT INTO silver.recon_exceptions VALUES (?, 'V', ?, ?, NULL, ?, 'OPEN', ?, ?, NULL, NULL, ?)",
            [exception_id, invoice, amount, reason, statement_id, raised, source_file],
        )


# ---------------------------------------------------------------------------
# A. Home -- get_recon_runs_panel()
# ---------------------------------------------------------------------------

class TestReconRunsPanel(_BackendTestCase):

    def test_status_filter_applies_before_the_row_cap(self):
        # 12 newer reconciled runs push the one exceptions run out of any
        # "newest 10" -- it must still come back under status=exceptions.
        for i in range(12):
            self._run(f"OK-{i:02d}", exception_count=0, ts=f"2026-09-{i + 10:02d}T00:00:00")
        self._run("EXC-OLD", exception_count=3, ts="2026-08-01T00:00:00")

        unfiltered = queries.get_recon_runs_panel(limit=10)
        self.assertNotIn("EXC-OLD", [r["statement_id"] for r in unfiltered["runs"]])

        panel = queries.get_recon_runs_panel(status="exceptions", limit=10)
        self.assertEqual([r["statement_id"] for r in panel["runs"]], ["EXC-OLD"])
        self.assertEqual((panel["reconciled"], panel["total"]), (0, 1))

    def test_reconciled_filter_keeps_only_zero_exception_runs(self):
        self._run("A", exception_count=0, ts="2026-09-03T00:00:00")
        self._run("B", exception_count=2, ts="2026-09-02T00:00:00")
        self._run("C", exception_count=0, ts="2026-09-01T00:00:00")

        panel = queries.get_recon_runs_panel(status="reconciled")
        self.assertEqual([r["statement_id"] for r in panel["runs"]], ["A", "C"])

    def test_counts_cover_every_matching_run_not_just_those_shown(self):
        for i in range(15):
            self._run(f"S-{i:02d}", exception_count=0 if i % 3 else 1, ts=f"2026-09-{i + 1:02d}T00:00:00")

        panel = queries.get_recon_runs_panel(limit=10)
        self.assertEqual(len(panel["runs"]), 10)
        self.assertEqual(panel["total"], 15)
        self.assertEqual(panel["reconciled"], 10)  # i = 1,2,4,5,7,8,10,11,13,14

    def test_period_filter_uses_intake_log_period(self):
        self._run("AUG", exception_count=0, ts="2026-09-02T00:00:00", period="2026-08", shop="Harbour")
        self._run("JUL", exception_count=1, ts="2026-09-01T00:00:00", period="2026-07")

        panel = queries.get_recon_runs_panel(period="2026-07")
        self.assertEqual([r["statement_id"] for r in panel["runs"]], ["JUL"])
        self.assertEqual((panel["reconciled"], panel["total"]), (0, 1))

        both = queries.get_recon_runs_panel(status="reconciled", period="2026-08")
        self.assertEqual([r["statement_id"] for r in both["runs"]], ["AUG"])
        self.assertEqual(both["runs"][0]["shop"], "Harbour")

    def test_period_options_are_only_periods_with_runs_newest_first(self):
        self._run("A", exception_count=0, ts="2026-09-03T00:00:00", period="2026-07")
        self._run("B", exception_count=1, ts="2026-09-02T00:00:00", period="2026-08")
        self._run("C", exception_count=0, ts="2026-09-01T00:00:00", period="2026-07")
        self._run("D", exception_count=0, ts="2026-09-01T00:00:00")  # no intake period
        # An intake row whose statement never reached recon_summary must not
        # add a period to the dropdown.
        self.local.execute("INSERT INTO document_intake_log VALUES ('ORPHAN', '2026-01', NULL)")

        panel = queries.get_recon_runs_panel(status="reconciled", period="2026-07")
        # Built from all runs, before either filter.
        self.assertEqual(panel["period_options"], ["2026-08", "2026-07"])

    def test_unknown_status_is_treated_as_all(self):
        self._run("A", exception_count=0, ts="2026-09-02T00:00:00")
        self._run("B", exception_count=1, ts="2026-09-01T00:00:00")
        panel = queries.get_recon_runs_panel(status="bogus")
        self.assertEqual(panel["total"], 2)

    def test_job_ids_are_looked_up_only_for_rows_shown(self):
        for i in range(12):
            self._run(f"S-{i:02d}", exception_count=0, ts=f"2026-09-{i + 1:02d}T00:00:00")
        self.local.execute("INSERT INTO jobs VALUES ('job-new', 'S-11', '2026-09-12')")
        panel = queries.get_recon_runs_panel(limit=10)
        self.assertEqual(panel["runs"][0]["job_id"], "job-new")
        self.assertTrue(all("job_id" in r for r in panel["runs"]))


class TestRecentReconRunsStillWorks(_BackendTestCase):

    def test_wrapper_returns_newest_rows_with_period_and_shop(self):
        self._run("OLD", exception_count=0, ts="2026-09-01T00:00:00", period="2026-07", shop="A")
        self._run("NEW", exception_count=1, ts="2026-09-02T00:00:00", period="2026-08", shop="B")
        rows = queries.get_recent_recon_runs(limit=1)
        self.assertEqual([r["statement_id"] for r in rows], ["NEW"])
        self.assertEqual((rows[0]["statement_period"], rows[0]["shop"]), ("2026-08", "B"))


# ---------------------------------------------------------------------------
# B. Exceptions review -- sort
# ---------------------------------------------------------------------------

class TestExceptionSort(_BackendTestCase):

    def setUp(self):
        super().setUp()
        self._exc("e1", amount=50.0, raised="2026-09-10T00:00:00", invoice="INV-B")
        self._exc("e2", amount=500.0, raised="2026-09-20T00:00:00", invoice="INV-C")
        self._exc("e3", amount=-25.0, raised="2026-08-01T00:00:00", invoice="INV-A",
                  reason="Amount Mismatch")

    def _ids(self, rows):
        return [r["exception_id"] for r in rows]

    def test_default_order_is_invoice_number(self):
        self.assertEqual(self._ids(queries.get_open_exceptions("STMT-1")), ["e3", "e1", "e2"])

    def test_amount_sort_is_largest_first_with_credits_last(self):
        self.assertEqual(self._ids(queries.get_open_exceptions("STMT-1", sort="amount")), ["e2", "e1", "e3"])

    def test_oldest_sort_is_date_raised_ascending(self):
        self.assertEqual(self._ids(queries.get_open_exceptions("STMT-1", sort="oldest")), ["e3", "e1", "e2"])

    def test_sort_combines_with_reason_filter(self):
        rows = queries.get_open_exceptions("STMT-1", reason_filter="missing", sort="amount")
        self.assertEqual(self._ids(rows), ["e2", "e1"])

    def test_unknown_sort_falls_back_to_default_and_is_never_interpolated(self):
        rows = queries.get_open_exceptions("STMT-1", sort="statement_amount; DROP TABLE x")
        self.assertEqual(self._ids(rows), ["e3", "e1", "e2"])

    def test_source_file_variant_sorts_too(self):
        self._exc("o1", amount=10.0, raised="2026-09-02T00:00:00", invoice="A", statement_id="ORPH",
                  source_file="orphan.pdf")
        self._exc("o2", amount=90.0, raised="2026-09-01T00:00:00", invoice="B", statement_id="ORPH",
                  source_file="orphan.pdf")
        self.assertEqual(self._ids(queries.get_open_exceptions_for_source_file("orphan.pdf")), ["o1", "o2"])
        self.assertEqual(self._ids(queries.get_open_exceptions_for_source_file("orphan.pdf", sort="amount")),
                         ["o2", "o1"])
        self.assertEqual(self._ids(queries.get_open_exceptions_for_source_file("orphan.pdf", sort="oldest")),
                         ["o2", "o1"])
        self.assertEqual(
            self._ids(queries.get_open_exceptions_for_source_file("orphan.pdf", reason_filter="missing",
                                                                  sort="oldest")),
            ["o2", "o1"],
        )


class TestFilterRedirectSuffixKeepsSort(unittest.TestCase):

    def test_sort_is_kept(self):
        self.assertEqual(_filter_redirect_suffix("missing", "STMT-1", "amount"),
                         "?filter=missing&statement_id=STMT-1&sort=amount")

    def test_default_sort_adds_nothing(self):
        self.assertEqual(_filter_redirect_suffix("all", "STMT-1", ""), "?statement_id=STMT-1")
        self.assertEqual(_filter_redirect_suffix("all", None, None), "")

    def test_unknown_sort_is_dropped(self):
        self.assertEqual(_filter_redirect_suffix("all", None, "evil"), "")


def _render_review(**overrides):
    exc = {
        "exception_id": "exc-1", "statement_id": "STMT-TEST", "invoice_number": "900CC752",
        "vendor_id": "V", "statement_amount": 158.55, "erp_amount": None,
        "exception_reason": "Not Found in NetSuite", "exception_status": "OPEN",
        "date_raised": "2026-09-21T16:45:51+00:00", "days_open": 7, "match_confidence": None,
        "escalation_status": None, "invoice_date": None, "ro_number": None,
    }
    ctx = {
        "active_page": "exceptions", "vendor_name": "Keystone", "vendor_display_name": "Keystone",
        "vendor_url_name": "Keystone", "not_found": False, "statement": {"statement_id": "STMT-TEST"},
        "exceptions": [exc], "selected": exc, "total": 1, "resolved": 0, "progress_pct": 0,
        "filter": "missing", "sort": "amount", "reason_badge": REASON_BADGE,
        "high_confidence_count": 0, "bulk_approve_threshold": 0.99, "netsuite_record": None,
        "searchable_reasons": SEARCHABLE_REASONS, "open_exception_count": 1, "user": "tester",
    }
    ctx.update(overrides)
    # Jinja autoescapes "&" to "&amp;" inside href values (browsers decode it
    # back) -- unescape so the assertions can compare plain URLs.
    return templates.get_template("exceptions_review.html").render(**ctx).replace("&amp;", "&")


class TestReviewPageCarriesSort(unittest.TestCase):

    def test_filter_tabs_keep_statement_and_sort(self):
        html = _render_review()
        for f in ("all", "missing", "mismatch"):
            self.assertIn(f'href="/exceptions/Keystone?filter={f}&statement_id=STMT-TEST&sort=amount"', html)

    def test_row_link_keeps_sort(self):
        html = _render_review()
        self.assertIn('href="/exceptions/Keystone?filter=missing&statement_id=STMT-TEST&sort=amount&selected=exc-1"',
                      html)

    def test_sort_chips_keep_filter_statement_and_selected(self):
        html = _render_review(sort="")
        base = "/exceptions/Keystone?filter=missing&statement_id=STMT-TEST&selected=exc-1"
        self.assertIn(f'href="{base}" class="filter-tab active">Invoice #', html)
        self.assertIn(f'href="{base}&sort=amount" class="filter-tab ">Largest amount', html)
        self.assertIn(f'href="{base}&sort=oldest" class="filter-tab ">Oldest first', html)

    def test_active_sort_chip_is_marked(self):
        html = _render_review(sort="oldest")
        self.assertIn('class="filter-tab active">Oldest first', html)
        self.assertIn('class="filter-tab ">Invoice #', html)

    def test_both_post_forms_carry_sort(self):
        html = _render_review(sort="oldest")
        self.assertEqual(html.count('<input type="hidden" name="sort" value="oldest">'), 2)

    def test_modal_still_has_no_form(self):
        html = _render_review()
        modal = html[html.index('<dialog class="ns-modal"'):html.index("</dialog>")]
        self.assertNotIn("<form", modal)


def _client(router):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(router)
    app.dependency_overrides[require_login] = lambda: "tester"
    return TestClient(app)


def _patch_all(testcase, **fns):
    for name, fn in fns.items():
        patcher = mock.patch(f"web.queries.{name}", fn)
        patcher.start()
        testcase.addCleanup(patcher.stop)


_SIDEBAR = {"get_open_recon_exceptions_count": lambda: 0, "get_pending_review_count": lambda: 0}


class TestReviewRouteSortWiring(unittest.TestCase):

    def setUp(self):
        self.calls = []

        def get_open_exceptions(statement_id, reason_filter=None, sort=None):
            self.calls.append(sort)
            return []

        _patch_all(
            self,
            get_statement_by_id=lambda sid: {"statement_id": sid},
            get_open_exceptions=get_open_exceptions,
            get_exception_counts=lambda sid: (0, 0),
            get_high_confidence_exception_count=lambda *a, **k: 0,
            resolve_exception=lambda **k: None,
            escalate_exception=lambda *a, **k: None,
            **_SIDEBAR,
        )
        self.client = _client(exceptions.router)

    def test_known_sort_reaches_the_query(self):
        resp = self.client.get("/exceptions/Keystone?statement_id=S1&sort=oldest")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.calls, ["oldest"])

    def test_unknown_sort_reaches_the_query_as_none(self):
        self.client.get("/exceptions/Keystone?statement_id=S1&sort=bogus")
        self.assertEqual(self.calls, [None])

    def test_accept_redirect_keeps_sort(self):
        resp = self.client.post("/exceptions/Keystone", data={
            "exception_id": "e1", "statement_id": "S1", "invoice_number": "I", "reason_code": "R",
            "action": "ACCEPTED", "filter": "mismatch", "sort": "amount",
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/exceptions/Keystone?filter=mismatch&statement_id=S1&sort=amount")

    def test_escalate_redirect_keeps_sort(self):
        resp = self.client.post("/exceptions/Keystone/escalate", data={
            "exception_id": "e1", "statement_id": "S1", "filter": "all", "sort": "oldest",
        }, follow_redirects=False)
        self.assertEqual(resp.headers["location"], "/exceptions/Keystone?statement_id=S1&sort=oldest")


# ---------------------------------------------------------------------------
# A. Home -- route + template
# ---------------------------------------------------------------------------

class TestHomeRoute(unittest.TestCase):

    def setUp(self):
        self.panel_calls = []

        def get_recon_runs_panel(status="all", period=None, limit=10):
            self.panel_calls.append((status, period, limit))
            return {
                "runs": [{"statement_id": "S1", "vendor_name": "Keystone", "vendor_display_name": "Keystone",
                          "shop": None, "statement_period": "2026-08", "total_invoice_count": 5,
                          "matched_count": 5, "exception_count": 0, "overall_status": "RECONCILED",
                          "reconciliation_timestamp": None, "job_id": None}],
                "total": 12, "reconciled": 7, "period_options": ["2026-08", "2026-07"],
            }

        _patch_all(
            self,
            get_recon_runs_panel=get_recon_runs_panel,
            get_kpis=lambda: {"total_invoices": 5556, "auto_reconciled": 5179, "open_exceptions": 0,
                              "statement_total": 0, "vendor_count": 3, "match_rate": 93.2,
                              "pending_review_count": 0},
            get_active_jobs=lambda: [], get_failed_jobs=lambda: [],
            get_recent_completed_batches=lambda limit=3: [],
            get_last_netsuite_sync=lambda: None, get_last_outlook_sync=lambda: None,
            **_SIDEBAR,
        )
        self.client = _client(dashboard.router)

    def test_filters_are_passed_through(self):
        resp = self.client.get("/?status=exceptions&period=2026-07")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.panel_calls, [("exceptions", "2026-07", 10)])

    def test_bad_status_becomes_all(self):
        self.client.get("/?status=nope")
        self.assertEqual(self.panel_calls, [("all", None, 10)])

    def test_n_of_m_and_reconciled_card(self):
        html = self.client.get("/").text
        self.assertIn("7 of 12 statements reconciled", html)
        self.assertIn("5,179", html)
        self.assertIn("of 5,556", html)
        self.assertIn("93.2% matched", html)

    def test_status_chips_keep_period_and_dropdown_keeps_status(self):
        html = self.client.get("/?status=reconciled&period=2026-07").text.replace("&amp;", "&")
        self.assertIn('href="/?status=all&period=2026-07" class="filter-chip "', html)
        self.assertIn('href="/?status=reconciled&period=2026-07" class="filter-chip active"', html)
        self.assertIn('<input type="hidden" name="status" value="reconciled">', html)
        self.assertIn('<option value="2026-07" selected>Jul 2026</option>', html)
        self.assertIn('<option value="2026-08" >Aug 2026</option>', html)


# ---------------------------------------------------------------------------
# C. Validation -- period filter
# ---------------------------------------------------------------------------

class TestValidationPeriodFilter(unittest.TestCase):

    def setUp(self):
        runs = [
            {"statement_id": "A", "source_file": "a.pdf", "vendor_name": "Keystone", "statement_period": "2026-07",
             "statement_total_as_printed": 10, "validation_status": "matches", "validation_difference": 0,
             "ingestion_timestamp": None, "shop": None, "passed": True},
            {"statement_id": "B", "source_file": "b.pdf", "vendor_name": "Keystone", "statement_period": "2026-08",
             "statement_total_as_printed": 10, "validation_status": "mismatch", "validation_difference": 1,
             "ingestion_timestamp": None, "shop": None, "passed": False},
            {"statement_id": "C", "source_file": "c.pdf", "vendor_name": "Keystone", "statement_period": None,
             "statement_total_as_printed": 10, "validation_status": "matches", "validation_difference": 0,
             "ingestion_timestamp": None, "shop": None, "passed": True},
        ]
        _patch_all(self, get_validation_report=lambda: [dict(r) for r in runs], **_SIDEBAR)
        self.html = _client(validation.router).get("/validation").text

    def test_dropdown_offers_only_periods_with_data_newest_first(self):
        options = re.findall(r'<select id="period-filter".*?</select>', self.html, re.DOTALL)[0]
        self.assertEqual(re.findall(r'<option value="([^"]*)"', options), ["", "2026-08", "2026-07"])
        self.assertIn(">Aug 2026<", options)

    def test_cards_carry_their_period(self):
        self.assertIn('data-period="2026-07"', self.html)
        self.assertIn('data-period="2026-08"', self.html)
        self.assertIn('data-period=""', self.html)

    def test_filter_script_checks_period(self):
        self.assertIn("card.dataset.period === period", self.html)

    def test_hero_summary_stays_unfiltered(self):
        self.assertIn('<div class="report-hero-stat-num">3</div>', self.html)


if __name__ == "__main__":
    unittest.main()
