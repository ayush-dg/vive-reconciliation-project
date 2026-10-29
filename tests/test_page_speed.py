"""
tests/test_page_speed.py

Page-speed changes (2026-10-29): the sidebar counts are kept for 30 minutes
instead of recounted on every page; Fabric read helpers reuse connections;
pages are gzip-compressed (statement PDFs excepted); versioned static files
are cached by the browser. Offline -- connections are fakes.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.testclient import TestClient

from src.lakehouse import fabric_sql
from web import deps


class SidebarCountsTests(unittest.TestCase):
    def setUp(self):
        deps._SIDEBAR_COUNTS.update(at=None, values=None)
        self.addCleanup(deps._SIDEBAR_COUNTS.update, at=None, values=None)
        self.request = mock.Mock(session={"user": "a@b.com", "user_name": "A"})

    def _context(self, now, ttl=None):
        env = {"SIDEBAR_COUNTS_TTL_SECONDS": ttl} if ttl else {}
        with mock.patch.dict(os.environ, env), mock.patch.object(deps.time, "monotonic", return_value=now), \
                mock.patch("web.queries.get_open_recon_exceptions_count", return_value=7) as open_count, \
                mock.patch("web.queries.get_pending_review_count", return_value=2) as pending:
            ctx = deps.sidebar_context(self.request)
        return ctx, open_count.call_count + pending.call_count

    def test_counted_once_then_kept_for_30_minutes(self):
        ctx, queries = self._context(now=1000.0)
        self.assertEqual((ctx["open_exceptions_count"], ctx["pending_review_count"], queries), (7, 2, 2))
        self.assertEqual(self._context(now=1000.0 + 1799)[1], 0)   # still fresh: no queries
        self.assertEqual(self._context(now=1000.0 + 1800)[1], 2)   # 30 min on: recounted

    def test_lifetime_is_a_setting(self):
        self._context(now=0.0, ttl="60")
        self.assertEqual(self._context(now=61.0, ttl="60")[1], 2)

    def test_user_fields_are_never_cached(self):
        self._context(now=0.0)
        self.request.session = {"user": "other@b.com"}
        ctx, _ = self._context(now=1.0)
        self.assertEqual(ctx["user_email"], "other@b.com")


class _Cur:
    def __init__(self, conn):
        self.conn, self.description = conn, [("c",)]
        conn.cursors.append(self)
        self.closed = False

    def execute(self, sql, params):
        if self.conn.fail:
            raise RuntimeError("connection dropped")

    def fetchall(self):
        return [(1,)]

    def close(self):
        self.closed = True


class _Conn:
    def __init__(self, fail=False):
        self.fail, self.closed, self.cursors = fail, False, []

    def cursor(self):
        return _Cur(self)

    def close(self):
        self.closed = True


class FabricPoolTests(unittest.TestCase):
    def setUp(self):
        fabric_sql._pools.clear()
        self.addCleanup(fabric_sql._pools.clear)
        self.made = []
        self.now = [100.0]
        patches = [
            mock.patch.object(fabric_sql, "_connect", side_effect=self._connect),
            mock.patch.object(fabric_sql.time, "monotonic", side_effect=lambda: self.now[0]),
            mock.patch.dict(os.environ, {"FABRIC_WAREHOUSE_NAME": "wh", "FABRIC_LAKEHOUSE_NAME": "lh"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _connect(self, database):
        conn = _Conn()
        self.made.append(conn)
        return conn

    def test_connection_is_reused_between_queries(self):
        for _ in range(5):
            self.assertEqual(fabric_sql.execute_warehouse_query("SELECT 1"), [{"c": 1}])
            self.now[0] += 10
        self.assertEqual(len(self.made), 1)
        # Every cursor is closed before its connection goes back for another thread.
        self.assertTrue(all(cur.closed for cur in self.made[0].cursors))

    def test_idle_connection_is_not_reused(self):
        fabric_sql.execute_warehouse_query("SELECT 1")
        self.now[0] += fabric_sql._POOL_IDLE_SECONDS
        fabric_sql.execute_warehouse_query("SELECT 1")
        self.assertEqual(len(self.made), 2)
        self.assertTrue(self.made[0].closed)

    def test_old_connection_is_not_reused(self):
        for _ in range(int(fabric_sql._POOL_MAX_AGE_SECONDS / 100) + 1):
            fabric_sql.execute_warehouse_query("SELECT 1")
            self.now[0] += 100  # in use every 100 s, so only the age retires it
        self.assertGreaterEqual(len(self.made), 2)

    def test_failure_on_a_reused_connection_retries_on_a_new_one(self):
        fabric_sql.execute_warehouse_query("SELECT 1")
        self.made[0].fail = True
        self.assertEqual(fabric_sql.execute_warehouse_query("SELECT 1"), [{"c": 1}])
        self.assertEqual(len(self.made), 2)
        self.assertTrue(self.made[0].closed)

    def test_failure_on_a_new_connection_is_raised(self):
        with mock.patch.object(fabric_sql, "_connect", side_effect=lambda db: _Conn(fail=True)):
            with self.assertRaises(RuntimeError):
                fabric_sql.execute_warehouse_query("SELECT 1")

    def test_lakehouse_and_warehouse_have_separate_pools(self):
        fabric_sql.execute_warehouse_query("SELECT 1")
        fabric_sql.execute_lakehouse_query("SELECT 1")
        self.assertEqual(len(self.made), 2)
        self.assertEqual(sorted(fabric_sql._pools), ["lh", "wh"])


class OpenExceptionsGroupedTests(unittest.TestCase):
    """Long statement-id lists are not sent to Fabric as IN (?, ?, ...) -- the
    open exceptions are grouped once and filtered here (same rows)."""

    ROWS = [{"statement_id": "S1", "c": 2}, {"statement_id": "S2", "c": 1}, {"statement_id": "OTHER", "c": 9}]

    def _run(self, ids):
        from web import queries
        with mock.patch.object(queries, "recon_query", return_value=self.ROWS) as q:
            rows = queries._open_exceptions_grouped("statement_id, COUNT(*) AS c", "statement_id", ids)
        return rows, q.call_args

    def test_a_short_list_is_sent_as_parameters(self):
        rows, call = self._run(["S1", "S2"])
        self.assertIn("IN (?, ?)", call.args[0])
        self.assertEqual(call.args[1], ["S1", "S2"])

    def test_a_long_list_is_filtered_here_instead(self):
        from web import queries
        ids = ["S1", "S2"] + [f"X{i}" for i in range(queries._IN_LIST_LIMIT)]
        rows, call = self._run(ids)
        self.assertNotIn(" IN (", call.args[0])
        self.assertEqual(len(call.args), 1)  # no parameters at all
        self.assertEqual([r["statement_id"] for r in rows], ["S1", "S2"])

    def test_no_ids_means_no_query(self):
        from web import queries
        with mock.patch.object(queries, "recon_query") as q:
            self.assertEqual(queries._open_exceptions_grouped("statement_id", "statement_id", []), [])
        q.assert_not_called()


class CompressionAndCachingTests(unittest.TestCase):
    def _client(self):
        from web.app import _GZipExceptStatementPdfs, _VersionedStaticFiles, STATIC_DIR
        app = FastAPI()
        app.add_middleware(_GZipExceptStatementPdfs)

        @app.get("/page")
        def page():
            return HTMLResponse("<p>" + "x" * 5000 + "</p>")

        @app.get("/statements/S1/statement.pdf")
        def pdf():
            return Response(b"%PDF-1.4" + b"0" * 5000, media_type="application/pdf")

        app.mount("/static", _VersionedStaticFiles(directory=STATIC_DIR), name="static")
        return TestClient(app)

    def test_pages_are_compressed(self):
        resp = self._client().get("/page", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(resp.headers.get("content-encoding"), "gzip")

    def test_statement_pdfs_are_not(self):
        resp = self._client().get("/statements/S1/statement.pdf", headers={"Accept-Encoding": "gzip"})
        self.assertIsNone(resp.headers.get("content-encoding"))

    def test_versioned_static_files_are_cached_for_a_year(self):
        client = self._client()
        versioned = client.get("/static/style.css?v=abc123")
        self.assertIn("max-age=31536000", versioned.headers.get("cache-control", ""))
        plain = client.get("/static/style.css")
        self.assertNotIn("max-age=31536000", plain.headers.get("cache-control", ""))


if __name__ == "__main__":
    unittest.main()
