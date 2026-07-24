"""
tests/test_batches.py

HTTP-level tests for GET /batches and GET /batches/{batch_id} -- login is
bypassed via FastAPI's dependency_overrides (no session middleware
wiring needed for that), but SessionMiddleware is still installed since
web.deps.sidebar_context() reads request.session directly. queries.py is
exercised against a real in-memory SQLite DB with the full migration
history applied, same convention as tests/test_web_queries.py.
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
from web.routers import batches
from src.lakehouse.migrations import apply_pending_migrations


def _make_db():
    # check_same_thread=False: FastAPI's TestClient runs the route handler
    # in a worker thread (via run_in_threadpool), but this fixture shares
    # one in-memory connection across the whole test -- the real app never
    # does this (src/lakehouse/connection.py opens a fresh connection per
    # call), so this relaxation is test-only.
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


class TestBatchesRoutes(unittest.TestCase):

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
        app.include_router(batches.router)
        app.dependency_overrides[require_login] = lambda: "tester"
        self.client = TestClient(app)

    def _job(self, job_id, batch_id, status, statement_id=None,
              submitted_at="2026-07-24T10:00:00+00:00", completed_at=None, filename=None):
        queries.create_job(job_id=job_id, pdf_filename=filename or f"{job_id}.pdf",
                            pdf_path=f"sample_data/{job_id}.pdf", submitted_by="tester",
                            batch_id=batch_id)
        self.execute_sql("UPDATE jobs SET submitted_at = ? WHERE job_id = ?", [submitted_at, job_id])
        queries.update_job_status(job_id, status=status, completed_at=completed_at, statement_id=statement_id)

    def test_batches_list_renders_with_no_data(self):
        resp = self.client.get("/batches")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("No auto-intake batches yet.", resp.text)
        self.assertIn("No manual uploads yet.", resp.text)

    def test_batches_list_shows_a_completed_batch_card(self):
        self._job("job-1", "batch-abc12345", "COMPLETED", statement_id="STMT-1",
                   completed_at="2026-07-24T10:02:00+00:00")

        resp = self.client.get("/batches")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("batch-ab", resp.text)  # first 8 chars of the batch_id
        self.assertIn("Completed", resp.text)

    def test_batches_list_shows_manual_uploads_grouped_by_date(self):
        self._job("manual-1", None, "COMPLETED", submitted_at="2026-07-24T09:00:00+00:00")

        resp = self.client.get("/batches")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("manual-1.pdf", resp.text)
        self.assertIn("2026-07-24", resp.text)

    def test_batch_detail_renders_files_and_links_to_report(self):
        self._job("job-1", "batch-xyz", "COMPLETED", statement_id="STMT-9",
                   completed_at="2026-07-24T10:02:00+00:00", filename="statement.pdf")

        resp = self.client.get("/batches/batch-xyz")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("statement.pdf", resp.text)
        self.assertIn("/reports/STMT-9", resp.text)

    def test_batch_detail_unknown_batch_id_redirects_to_batches_list(self):
        resp = self.client.get("/batches/does-not-exist", follow_redirects=False)

        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/batches")


if __name__ == "__main__":
    unittest.main()
