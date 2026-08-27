"""
tests/test_exceptions_escalate.py

HTTP-level tests for POST /exceptions/{vendor_name}/escalate and the
aging/escalation display on exceptions_review.html (detail panel) and
exceptions_vendors.html (vendor card "Oldest: N days open" note).

Also covers the same routing-order requirement as bulk-approve
(tests/test_exceptions_bulk_approve.py): /escalate must be registered
ahead of the greedy POST /exceptions/{vendor_name:path} action route.
"""

import os
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from web import queries
from web.deps import require_login
from web.routers import exceptions
from src.lakehouse.migrations import apply_pending_migrations


def _make_db():
    # check_same_thread=False: TestClient runs the route handler in a
    # worker thread (see tests/test_batches.py for the same fixture).
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    return conn


def _wire_fake_backend(conn):
    def execute_sql(sql, params=None):
        cur = conn.execute(sql, params or [])
        conn.commit()
        return cur

    def execute_query(sql, params=None):
        cur = conn.execute(sql, params or [])
        return [dict(row) for row in cur.fetchall()]

    return execute_sql, execute_query


def _raised_days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _insert_gold_summary(execute_sql, *, statement_id, vendor_name):
    execute_sql(
        """
        INSERT INTO gold_reconciliation_summary (
            summary_id, vendor_id, vendor_name, statement_period, statement_id,
            statement_total, erp_total, difference, total_invoice_count,
            matched_count, exception_count, match_percentage, overall_status,
            reconciliation_timestamp, erp_version
        ) VALUES (?, 'V1', ?, '2026-07', ?, 1000.0, 1000.0, 0.0, 3, 3, 0, 100.0,
                  'RECONCILED', '2026-07-24T00:00:00+00:00', 1)
        """,
        [f"SUM-{statement_id}", vendor_name, statement_id],
    )


def _insert_gold_exception(execute_sql, *, statement_id, exception_id, invoice_number, date_raised):
    execute_sql(
        """
        INSERT INTO gold_exceptions (
            exception_id, vendor_id, invoice_number, statement_amount, erp_amount,
            match_status, exception_reason, exception_status, statement_id, date_raised
        ) VALUES (?, 'V1', ?, 100.0, NULL, 'EXCEPTION', 'Invoice Missing', 'OPEN', ?, ?)
        """,
        [exception_id, invoice_number, statement_id, date_raised],
    )


class TestEscalateRoute(unittest.TestCase):

    def setUp(self):
        self.conn = _make_db()
        self.execute_sql, self.execute_query = _wire_fake_backend(self.conn)
        patcher1 = mock.patch("web.queries.execute_sql", self.execute_sql)
        patcher2 = mock.patch("web.queries.execute_query", self.execute_query)
        patcher1.start()
        patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)
        self.addCleanup(self.conn.close)

        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret")
        app.include_router(exceptions.router)
        app.dependency_overrides[require_login] = lambda: "reviewer@vive.com"
        self.client = TestClient(app)

        _insert_gold_summary(self.execute_sql, statement_id="STMT-1", vendor_name="Vendor One")
        _insert_gold_exception(self.execute_sql, statement_id="STMT-1", exception_id="EXC-1",
                                invoice_number="INV-1", date_raised=_raised_days_ago(5))

    def test_escalate_redirects_back_to_vendor(self):
        resp = self.client.post(
            "/exceptions/Vendor%20One/escalate",
            data={"exception_id": "EXC-1"},
            follow_redirects=False,
        )

        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/exceptions/Vendor%20One")

    def test_escalate_sets_status_and_metadata(self):
        self.client.post("/exceptions/Vendor%20One/escalate", data={"exception_id": "EXC-1"})

        row = self.execute_query("SELECT * FROM gold_exceptions WHERE exception_id = 'EXC-1'")[0]
        self.assertEqual(row["escalation_status"], "ESCALATED")
        self.assertEqual(row["escalated_by"], "reviewer@vive.com")
        self.assertEqual(row["exception_status"], "OPEN")  # escalating doesn't resolve it

    def test_escalate_preserves_filter_query_param(self):
        resp = self.client.post(
            "/exceptions/Vendor%20One/escalate",
            data={"exception_id": "EXC-1", "filter": "missing"},
            follow_redirects=False,
        )

        self.assertEqual(resp.headers["location"], "/exceptions/Vendor%20One?filter=missing")

    def test_escalate_does_not_get_swallowed_by_the_generic_action_route(self):
        """Regression guard: same greedy-path-converter risk as
        bulk-approve -- see test_exceptions_bulk_approve.py."""
        resp = self.client.post("/exceptions/Vendor%20One/escalate", data={"exception_id": "EXC-1"})

        self.assertNotEqual(resp.status_code, 422)


class TestAgingDisplay(unittest.TestCase):
    """exceptions_review.html shows "Open for X days" and an Escalate
    button (or "Escalated X days ago" once escalated), color-coded."""

    def setUp(self):
        self.conn = _make_db()
        self.execute_sql, self.execute_query = _wire_fake_backend(self.conn)
        patcher1 = mock.patch("web.queries.execute_sql", self.execute_sql)
        patcher2 = mock.patch("web.queries.execute_query", self.execute_query)
        patcher1.start()
        patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)
        self.addCleanup(self.conn.close)

        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret")
        app.include_router(exceptions.router)
        app.dependency_overrides[require_login] = lambda: "reviewer@vive.com"
        self.client = TestClient(app)

        _insert_gold_summary(self.execute_sql, statement_id="STMT-2", vendor_name="Vendor Two")

    def test_shows_open_for_days_and_escalate_button_when_not_escalated(self):
        _insert_gold_exception(self.execute_sql, statement_id="STMT-2", exception_id="EXC-1",
                                invoice_number="INV-1", date_raised=_raised_days_ago(3))

        resp = self.client.get("/exceptions/Vendor%20Two")

        self.assertIn("Open for 3 days", resp.text)
        self.assertIn("Escalate", resp.text)
        self.assertNotIn("Escalated", resp.text)

    def test_shows_escalated_message_instead_of_button_once_escalated(self):
        _insert_gold_exception(self.execute_sql, statement_id="STMT-2", exception_id="EXC-1",
                                invoice_number="INV-1", date_raised=_raised_days_ago(20))
        self.execute_sql(
            "UPDATE gold_exceptions SET escalation_status = 'ESCALATED', escalated_at = ?, escalated_by = ? "
            "WHERE exception_id = 'EXC-1'",
            [_raised_days_ago(2), "someone@vive.com"],
        )

        resp = self.client.get("/exceptions/Vendor%20Two")

        self.assertIn("Escalated 2 days ago", resp.text)
        self.assertNotIn('>🚩 Escalate<', resp.text)

    def test_aging_badge_color_under_7_days_is_neutral(self):
        _insert_gold_exception(self.execute_sql, statement_id="STMT-2", exception_id="EXC-1",
                                invoice_number="INV-1", date_raised=_raised_days_ago(2))

        resp = self.client.get("/exceptions/Vendor%20Two")

        self.assertIn("badge neutral", resp.text)

    def test_aging_badge_color_between_7_and_14_days_is_amber(self):
        _insert_gold_exception(self.execute_sql, statement_id="STMT-2", exception_id="EXC-1",
                                invoice_number="INV-1", date_raised=_raised_days_ago(10))

        resp = self.client.get("/exceptions/Vendor%20Two")

        self.assertIn("Open for 10 days", resp.text)
        self.assertIn("badge warning", resp.text)

    def test_aging_badge_color_over_14_days_is_red(self):
        _insert_gold_exception(self.execute_sql, statement_id="STMT-2", exception_id="EXC-1",
                                invoice_number="INV-1", date_raised=_raised_days_ago(20))

        resp = self.client.get("/exceptions/Vendor%20Two")

        self.assertIn("Open for 20 days", resp.text)
        self.assertIn("badge danger", resp.text)


class TestVendorListAgingDisplay(unittest.TestCase):
    """exceptions_vendors.html shows "Oldest: N days open" per vendor card."""

    def setUp(self):
        self.conn = _make_db()
        self.execute_sql, self.execute_query = _wire_fake_backend(self.conn)
        patcher1 = mock.patch("web.queries.execute_sql", self.execute_sql)
        patcher2 = mock.patch("web.queries.execute_query", self.execute_query)
        patcher1.start()
        patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)
        self.addCleanup(self.conn.close)

        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret")
        app.include_router(exceptions.router)
        app.dependency_overrides[require_login] = lambda: "reviewer@vive.com"
        self.client = TestClient(app)

    def test_vendor_card_shows_oldest_open_exception_age(self):
        _insert_gold_summary(self.execute_sql, statement_id="STMT-3", vendor_name="Vendor Three")
        _insert_gold_exception(self.execute_sql, statement_id="STMT-3", exception_id="EXC-1",
                                invoice_number="INV-1", date_raised=_raised_days_ago(5))

        resp = self.client.get("/exceptions")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Oldest: 5 days open", resp.text)

    def test_vendor_card_omits_aging_note_when_no_open_exceptions(self):
        _insert_gold_summary(self.execute_sql, statement_id="STMT-4", vendor_name="Vendor Four")

        resp = self.client.get("/exceptions")

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Oldest:", resp.text)


if __name__ == "__main__":
    unittest.main()
