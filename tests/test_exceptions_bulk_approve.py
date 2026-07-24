"""
tests/test_exceptions_bulk_approve.py

HTTP-level tests for POST /exceptions/{vendor_name}/bulk-approve. Also
covers the routing-order requirement noted in web/routers/exceptions.py:
this route must be registered ahead of the greedy
POST /exceptions/{vendor_name:path} action route, or Starlette's "path"
converter would swallow "/bulk-approve" into vendor_name and this
endpoint would never be reached.
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


def _insert_gold_exception(execute_sql, *, statement_id, exception_id, invoice_number, ai_confidence_score):
    execute_sql(
        """
        INSERT INTO gold_exceptions (
            exception_id, vendor_id, invoice_number, statement_amount, erp_amount,
            match_status, exception_reason, exception_status, statement_id, date_raised,
            ai_confidence_score
        ) VALUES (?, 'V1', ?, 100.0, NULL, 'EXCEPTION', 'Invoice Missing', 'OPEN', ?,
                  '2026-07-24T00:00:00+00:00', ?)
        """,
        [exception_id, invoice_number, statement_id, ai_confidence_score],
    )


class TestBulkApproveRoute(unittest.TestCase):

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
                                invoice_number="INV-1", ai_confidence_score=0.995)
        _insert_gold_exception(self.execute_sql, statement_id="STMT-1", exception_id="EXC-2",
                                invoice_number="INV-2", ai_confidence_score=0.50)

    def test_bulk_approve_only_resolves_qualifying_exceptions(self):
        resp = self.client.post("/exceptions/Vendor%20One/bulk-approve")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"approved": 1})

        rows = self.execute_query("SELECT exception_id, exception_status FROM gold_exceptions ORDER BY exception_id")
        self.assertEqual(rows[0]["exception_status"], "RESOLVED")  # EXC-1, 0.995 >= 0.99
        self.assertEqual(rows[1]["exception_status"], "OPEN")      # EXC-2, 0.50 < 0.99

    def test_bulk_approve_respects_custom_threshold_query_param(self):
        resp = self.client.post("/exceptions/Vendor%20One/bulk-approve?threshold=0.4")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"approved": 2})

    def test_bulk_approve_does_not_get_swallowed_by_the_generic_action_route(self):
        """Regression guard: if route registration order ever regresses,
        this POST would be caught by the generic
        POST /exceptions/{vendor_name:path} action route instead, which
        requires Form fields this request doesn't send -- FastAPI would
        respond 422, not the {"approved": ...} JSON body this route
        returns."""
        resp = self.client.post("/exceptions/Vendor%20One/bulk-approve")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("approved", resp.json())

    def test_get_review_page_shows_bulk_approve_button_when_high_confidence_exceptions_exist(self):
        resp = self.client.get("/exceptions/Vendor%20One")

        self.assertEqual(resp.status_code, 200)
        # The <script> block's getElementById("bulk-approve-btn") call is
        # always present, so assert on the actual button element (its id
        # attribute), not the bare id string.
        self.assertIn('id="bulk-approve-btn"', resp.text)
        self.assertIn("Approve 1 at 99%+ confidence", resp.text)

    def test_get_review_page_hides_bulk_approve_button_when_none_qualify(self):
        self.execute_sql("UPDATE gold_exceptions SET ai_confidence_score = 0.1")

        resp = self.client.get("/exceptions/Vendor%20One")

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('id="bulk-approve-btn"', resp.text)


if __name__ == "__main__":
    unittest.main()
