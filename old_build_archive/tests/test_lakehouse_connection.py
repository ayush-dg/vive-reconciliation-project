"""
tests/test_lakehouse_connection.py

Tests for the Azure SQL connection-drop retry logic in
src/lakehouse/connection.py (_is_dropped_connection_error, _run_with_retry,
and execute_sql/execute_query routing through it). No real DB or network
calls -- fake connections/cursors and pyodbc error objects constructed
directly (pyodbc is a real, already-installed dependency; no ODBC driver
or server needed just to build an exception instance).
"""

import os
import sys
import unittest
from unittest import mock

import pyodbc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse import connection


def _dropped_connection_error(sqlstate="08S01"):
    return pyodbc.OperationalError(sqlstate, f"[{sqlstate}] Communication link failure")


class TestIsDroppedConnectionError(unittest.TestCase):

    def test_recognizes_08s01(self):
        self.assertTrue(connection._is_dropped_connection_error(_dropped_connection_error("08S01")))

    def test_recognizes_08001(self):
        self.assertTrue(connection._is_dropped_connection_error(_dropped_connection_error("08001")))

    def test_rejects_other_pyodbc_sqlstate(self):
        err = pyodbc.ProgrammingError("42000", "[42000] Syntax error or access violation")
        self.assertFalse(connection._is_dropped_connection_error(err))

    def test_rejects_non_pyodbc_exception(self):
        self.assertFalse(connection._is_dropped_connection_error(ValueError("boom")))
        self.assertFalse(connection._is_dropped_connection_error(sqlite3_operational_error()))

    def test_rejects_pyodbc_error_with_no_args(self):
        self.assertFalse(connection._is_dropped_connection_error(pyodbc.Error()))


def sqlite3_operational_error():
    import sqlite3
    return sqlite3.OperationalError("database is locked")


class FakeConnection:
    """Minimal connection stand-in: .execute() consumes one scripted
    result (a return value, or an exception to raise) per call.
    .commit()/.close() just record that they happened."""

    def __init__(self, result):
        self._result = result
        self.closed = False
        self.committed = False

    def execute(self, sql, params=None):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class TestRunWithRetry(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch("src.lakehouse.connection.time.sleep", return_value=None)
        self.mock_sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def test_succeeds_on_first_attempt_no_retry(self):
        conns = [FakeConnection("ok")]
        with mock.patch("src.lakehouse.connection.get_connection", side_effect=conns):
            result = connection._run_with_retry(lambda conn: conn.execute("SELECT 1"))
        self.assertEqual(result, "ok")
        self.mock_sleep.assert_not_called()
        self.assertTrue(conns[0].closed)

    def test_retries_on_dropped_connection_then_succeeds(self):
        conns = [
            FakeConnection(_dropped_connection_error()),
            FakeConnection(_dropped_connection_error()),
            FakeConnection("ok"),
        ]
        with mock.patch("src.lakehouse.connection.get_connection", side_effect=conns):
            result = connection._run_with_retry(lambda conn: conn.execute("SELECT 1"))
        self.assertEqual(result, "ok")
        self.assertEqual(self.mock_sleep.call_count, 2)
        self.mock_sleep.assert_called_with(connection.CONNECTION_RETRY_WAIT_SECONDS)
        # every dropped connection was closed, never reused for the retry
        self.assertTrue(conns[0].closed)
        self.assertTrue(conns[1].closed)

    def test_gives_up_after_max_retries_and_raises_original_exception(self):
        conns = [FakeConnection(_dropped_connection_error()) for _ in range(connection.MAX_CONNECTION_RETRIES + 1)]
        with mock.patch("src.lakehouse.connection.get_connection", side_effect=conns):
            with self.assertRaises(pyodbc.OperationalError) as ctx:
                connection._run_with_retry(lambda conn: conn.execute("SELECT 1"))
        self.assertEqual(ctx.exception.args[0], "08S01")
        self.assertEqual(self.mock_sleep.call_count, connection.MAX_CONNECTION_RETRIES)
        self.assertTrue(all(c.closed for c in conns))

    def test_non_connection_error_raises_immediately_without_retry(self):
        conns = [FakeConnection(ValueError("bad SQL"))]
        with mock.patch("src.lakehouse.connection.get_connection", side_effect=conns):
            with self.assertRaises(ValueError):
                connection._run_with_retry(lambda conn: conn.execute("SELECT 1"))
        self.mock_sleep.assert_not_called()
        self.assertEqual(len(conns), 1)  # only one connection ever opened

    def test_logs_each_retry_attempt(self):
        conns = [
            FakeConnection(_dropped_connection_error()),
            FakeConnection(_dropped_connection_error()),
            FakeConnection("ok"),
        ]
        with mock.patch("src.lakehouse.connection.get_connection", side_effect=conns), \
                mock.patch("builtins.print") as mock_print:
            connection._run_with_retry(lambda conn: conn.execute("SELECT 1"))
        messages = [call.args[0] for call in mock_print.call_args_list]
        self.assertTrue(any("Azure SQL connection dropped" in m and "attempt 1/3" in m for m in messages))
        self.assertTrue(any("Azure SQL connection dropped" in m and "attempt 2/3" in m for m in messages))


class TestExecuteSqlAndExecuteQueryRetryIntegration(unittest.TestCase):
    """Confirms execute_sql/execute_query themselves route through
    _run_with_retry, not just that the helper works in isolation."""

    def setUp(self):
        patcher = mock.patch("src.lakehouse.connection.time.sleep", return_value=None)
        self.mock_sleep = patcher.start()
        self.addCleanup(patcher.stop)
        self._had_azure_server = os.environ.pop("AZURE_SQL_SERVER", None)

    def tearDown(self):
        if self._had_azure_server is not None:
            os.environ["AZURE_SQL_SERVER"] = self._had_azure_server

    def test_execute_sql_retries_and_succeeds(self):
        good_cursor = object()
        conns = [
            FakeConnection(_dropped_connection_error()),
            FakeConnection(good_cursor),
        ]
        with mock.patch("src.lakehouse.connection.get_connection", side_effect=conns):
            cursor = connection.execute_sql("INSERT INTO t (a) VALUES (?)", [1])
        self.assertIs(cursor, good_cursor)
        self.assertEqual(self.mock_sleep.call_count, 1)
        self.assertTrue(conns[1].committed)

    def test_execute_query_retries_and_succeeds_on_azure_path(self):
        class FakeCursor:
            description = [("col",)]

            def fetchall(self):
                return [("row1",)]

        os.environ["AZURE_SQL_SERVER"] = "fake-server"
        try:
            conns = [
                FakeConnection(_dropped_connection_error()),
                FakeConnection(FakeCursor()),
            ]
            with mock.patch("src.lakehouse.connection.get_connection", side_effect=conns):
                rows = connection.execute_query("SELECT a FROM t")
            self.assertEqual(rows, [{"col": "row1"}])
            self.assertEqual(self.mock_sleep.call_count, 1)
        finally:
            os.environ.pop("AZURE_SQL_SERVER", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
