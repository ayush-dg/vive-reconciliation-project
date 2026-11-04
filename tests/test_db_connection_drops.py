"""
tests/test_db_connection_drops.py

2026-11-04: /exceptions and /validation returned Internal Server Error when
the Fabric connection dropped (TCP Provider error 0x20). The pooled query
retried a failed reused connection on *another pooled one*, dead from the
same drop, and a dropped brand-new connection was never retried. Azure SQL's
retry also skipped a drop while opening the connection (error 0x68).

Now: a failure on a reused connection empties the pool and retries on new
connections; a dropped new connection (or connect) is retried; and a drop
that outlasts every retry shows a "try again" page (503), not a 500.
"""

import os
import sys
import unittest
from unittest import mock

import pyodbc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from src.lakehouse import connection, fabric_sql


def _dropped(sqlstate="08S01"):
    return pyodbc.OperationalError(sqlstate, f"[{sqlstate}] TCP Provider: Error code 0x20 (32)")


class _Cur:
    def __init__(self, conn):
        self.conn, self.description = conn, [("c",)]

    def execute(self, sql, params):
        if self.conn.error is not None:
            raise self.conn.error

    def fetchall(self):
        return [(1,)]

    def close(self):
        pass


class _Conn:
    def __init__(self, error=None):
        self.error, self.closed = error, False

    def cursor(self):
        return _Cur(self)

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class FabricPoolDropTests(unittest.TestCase):
    def setUp(self):
        fabric_sql._pools.clear()
        self.addCleanup(fabric_sql._pools.clear)
        patches = [
            mock.patch.object(fabric_sql.time, "sleep"),
            mock.patch.dict(os.environ, {"FABRIC_WAREHOUSE_NAME": "wh"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _pool(self, *conns):
        now = fabric_sql.time.monotonic()
        fabric_sql._pools["wh"] = [(c, now, now) for c in conns]

    def test_every_pooled_connection_dead_retries_on_a_new_one(self):
        dead = [_Conn(_dropped()), _Conn(_dropped())]
        self._pool(*dead)
        fresh = _Conn()
        with mock.patch.object(fabric_sql, "_connect", return_value=fresh) as connect:
            self.assertEqual(fabric_sql.execute_warehouse_query("SELECT 1"), [{"c": 1}])
        connect.assert_called_once_with("wh")
        self.assertTrue(all(c.closed for c in dead))
        self.assertEqual([c for c, _, _ in fabric_sql._pools["wh"]], [fresh])

    def test_a_dropped_new_connection_is_retried(self):
        conns = [_Conn(_dropped()), _Conn(_dropped("08001")), _Conn()]
        with mock.patch.object(fabric_sql, "_connect", side_effect=conns):
            self.assertEqual(fabric_sql.execute_warehouse_query("SELECT 1"), [{"c": 1}])
        self.assertTrue(conns[0].closed and conns[1].closed)

    def test_a_drop_while_connecting_is_retried(self):
        fresh = _Conn()
        with mock.patch.object(fabric_sql, "_connect", side_effect=[_dropped("08001"), fresh]):
            self.assertEqual(fabric_sql.execute_warehouse_query("SELECT 1"), [{"c": 1}])

    def test_a_drop_on_every_attempt_is_raised(self):
        conns = [_Conn(_dropped()) for _ in range(fabric_sql._QUERY_ATTEMPTS)]
        with mock.patch.object(fabric_sql, "_connect", side_effect=conns):
            with self.assertRaises(pyodbc.OperationalError):
                fabric_sql.execute_warehouse_query("SELECT 1")
        self.assertTrue(all(c.closed for c in conns))

    def test_a_query_error_on_a_new_connection_is_not_retried(self):
        bad = _Conn(pyodbc.ProgrammingError("42S02", "[42S02] Invalid object name"))
        with mock.patch.object(fabric_sql, "_connect", side_effect=[bad]) as connect:
            with self.assertRaises(pyodbc.ProgrammingError):
                fabric_sql.execute_warehouse_query("SELECT 1")
        self.assertEqual(connect.call_count, 1)


class AzureSqlConnectDropTests(unittest.TestCase):
    def test_a_drop_while_connecting_is_retried(self):
        conn = mock.Mock()
        with mock.patch("src.lakehouse.connection.time.sleep"), \
                mock.patch("src.lakehouse.connection.get_connection",
                           side_effect=[_dropped("08001"), conn]):
            self.assertEqual(connection._run_with_retry(lambda c: "ok"), "ok")
        conn.close.assert_called_once()


class DatabaseDownPageTests(unittest.TestCase):
    def setUp(self):
        from web.app import app

        self.app = app
        self.client = TestClient(app, raise_server_exceptions=False)

    def _get(self, error):
        path = f"/_test_db_error_{id(error)}"

        def route():
            raise error

        self.app.add_api_route(path, route)
        self.addCleanup(lambda: self.app.router.routes.pop())
        return self.client.get(path)

    def test_a_connection_that_stays_down_shows_a_try_again_page(self):
        response = self._get(_dropped())
        self.assertEqual(response.status_code, 503)
        self.assertIn("The database didn't answer", response.text)

    def test_other_database_errors_are_still_500(self):
        response = self._get(pyodbc.ProgrammingError("42S02", "[42S02] Invalid object name"))
        self.assertEqual(response.status_code, 500)


if __name__ == "__main__":
    unittest.main()
