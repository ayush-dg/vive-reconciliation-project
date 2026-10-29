"""
tests/test_netsuite_connect_client.py

Offline tests for src/netsuite/connect_client.py: settings, the one-time TBA
password, the connection string, the read-only guard, connection reuse /
refresh / reconnect, the idle reconnect and the query timeout (2026-10-29).
No ODBC driver or NetSuite call is used -- connections are fakes.
"""

import base64
import hashlib
import hmac
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.netsuite.connect_client import (
    ConnectClient,
    ConnectConfigError,
    QueryTimeout,
    ReadOnlyError,
    account_forms,
    build_password,
    check_read_only,
    connection_string,
    load_config,
)

_ENV = {
    "NETSUITE_CONNECT_ACCOUNT_ID": "7321761",
    "NETSUITE_CONNECT_CONSUMER_KEY": "ck",
    "NETSUITE_CONNECT_CONSUMER_SECRET": "cs",
    "NETSUITE_CONNECT_TOKEN_ID": "ti",
    "NETSUITE_CONNECT_TOKEN_SECRET": "ts",
    "NETSUITE_CONNECT_ROLE_ID": "1135",
}


class SettingsTests(unittest.TestCase):
    def test_production_and_sandbox_account_forms(self):
        self.assertEqual(account_forms("7321761"), ("7321761", "7321761"))
        self.assertEqual(account_forms("7321761_SB1"), ("7321761-sb1", "7321761_SB1"))
        self.assertEqual(account_forms(" 7321761-sb1 "), ("7321761-sb1", "7321761_SB1"))

    def test_bad_account_id_is_refused(self):
        with self.assertRaises(ConnectConfigError):
            account_forms("not-an-account")

    def test_missing_settings_are_all_named(self):
        with self.assertRaises(ConnectConfigError) as ctx:
            load_config({"NETSUITE_CONNECT_ACCOUNT_ID": "7321761"})
        for name in ("CONSUMER_KEY", "CONSUMER_SECRET", "TOKEN_ID", "TOKEN_SECRET", "ROLE_ID"):
            self.assertIn("NETSUITE_CONNECT_" + name, str(ctx.exception))

    def test_role_id_must_be_a_number(self):
        with self.assertRaises(ConnectConfigError):
            load_config({**_ENV, "NETSUITE_CONNECT_ROLE_ID": "Administrator"})

    def test_defaults(self):
        cfg = load_config(_ENV)
        self.assertEqual(cfg["host"], "7321761.connect.api.netsuite.com")
        self.assertEqual(cfg["max_age_seconds"], 1800)
        self.assertEqual(cfg["idle_seconds"], 60)
        self.assertEqual(cfg["account"], "7321761")

    def test_idle_seconds_can_be_set(self):
        self.assertEqual(load_config({**_ENV, "NETSUITE_CONNECT_IDLE_SECONDS": "30"})["idle_seconds"], 30)
        with self.assertRaises(ConnectConfigError):
            load_config({**_ENV, "NETSUITE_CONNECT_IDLE_SECONDS": "soon"})

    def test_host_driver_and_truststore_can_be_overridden(self):
        cfg = load_config({**_ENV, "NETSUITE_CONNECT_HOST": "h.example", "NETSUITE_CONNECT_DRIVER": "D",
                           "NETSUITE_CONNECT_TRUSTSTORE": "/x.cer", "NETSUITE_CONNECT_MAX_AGE_SECONDS": "60"})
        self.assertEqual((cfg["host"], cfg["driver"], cfg["truststore"], cfg["max_age_seconds"]),
                         ("h.example", "D", "/x.cer", 60))


class PasswordTests(unittest.TestCase):
    def test_signature_matches_tba_spec(self):
        cfg = load_config(_ENV)
        pwd = build_password(cfg, nonce="abc", timestamp="1700000000")
        base = "7321761&ck&ti&abc&1700000000"
        sig = base64.b64encode(hmac.new(b"cs&ts", base.encode(), hashlib.sha256).digest()).decode()
        self.assertEqual(pwd, f"{base}&{sig}&HMAC-SHA256")

    def test_every_password_is_different(self):
        cfg = load_config(_ENV)
        self.assertNotEqual(build_password(cfg), build_password(cfg))

    def test_connection_string_carries_account_role_and_truststore(self):
        cfg = load_config({**_ENV, "NETSUITE_CONNECT_DRIVER": "NetSuite ODBC Drivers 9.0",
                           "NETSUITE_CONNECT_TRUSTSTORE": "/opt/netsuite/odbcclient/cert/ca4.cer"})
        s = connection_string(cfg, "PW")
        for part in ("DRIVER={NetSuite ODBC Drivers 9.0}", "Host=7321761.connect.api.netsuite.com", "Port=1708",
                     "Encrypted=1", "SDSN=NetSuite2.com", "Truststore=/opt/netsuite/odbcclient/cert/ca4.cer",
                     "UID=TBA", "PWD=PW", "CustomProperties=AccountID=7321761;RoleID=1135"):
            self.assertIn(part, s)


class ReadOnlyTests(unittest.TestCase):
    def test_select_and_with_are_allowed(self):
        check_read_only("SELECT 1 FROM vendor")
        check_read_only("  -- a comment\n select id from transaction;")
        check_read_only("WITH x AS (SELECT 1 AS a) SELECT a FROM x")

    def test_writes_and_multiple_statements_are_refused(self):
        for sql in ("UPDATE transaction SET memo = 'x'", "DELETE FROM vendor", "INSERT INTO t VALUES (1)",
                    "SELECT 1; DELETE FROM vendor", "/* SELECT */ DROP TABLE x", ""):
            with self.assertRaises(ReadOnlyError, msg=sql):
                check_read_only(sql)


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = [("ID",), ("TranId",)]

    def execute(self, sql, params):
        self.conn.executed.append(sql)
        if self.conn.hang is not None:
            self.conn.hang.wait(5)  # a dead socket: waits until released (or 5s)
        if self.conn.fail_next:
            self.conn.fail_next -= 1
            raise RuntimeError("connection dropped")

    def fetchall(self):
        return [(1, "A1")]


class _Conn:
    def __init__(self, fail_next=0, hang=None):
        self.executed, self.closed, self.fail_next, self.hang = [], False, fail_next, hang

    def cursor(self):
        return _Cursor(self)

    def close(self):
        self.closed = True


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        self.made = []
        self.fail_first_query_on_first_conn = 0

        def connect(conn_str, timeout):
            self.assertIn("PWD=7321761&ck&ti&", conn_str)
            conn = _Conn(fail_next=self.fail_first_query_on_first_conn if not self.made else 0)
            self.made.append(conn)
            return conn

        self.client = ConnectClient(load_config(_ENV), connect_fn=connect, clock=self.clock)

    def test_rows_come_back_as_lowercase_dicts(self):
        self.assertEqual(self.client.query("SELECT id, tranid FROM transaction"), [{"id": 1, "tranid": "A1"}])

    def test_connection_is_reused_while_in_use(self):
        # 30s apart: never idle for the 60s that forces a new connection.
        for _ in range(5):
            self.client.query("SELECT 1 FROM vendor")
            self.clock.now += 30
        self.assertEqual(len(self.made), 1)
        self.assertEqual(self.client.logins, 1)

    def test_connection_is_refreshed_after_max_age(self):
        for _ in range(60):  # in use every 30s, so only the age forces it
            self.client.query("SELECT 1 FROM vendor")
            self.clock.now += 30
        self.client.query("SELECT 1 FROM vendor")
        self.assertEqual(len(self.made), 2)
        self.assertTrue(self.made[0].closed)

    def test_a_failed_query_is_retried_once_on_a_new_connection(self):
        self.fail_first_query_on_first_conn = 1
        self.assertEqual(self.client.query("SELECT 1 FROM vendor"), [{"id": 1, "tranid": "A1"}])
        self.assertEqual(len(self.made), 2)
        self.assertTrue(self.made[0].closed)

    def test_a_second_failure_is_raised(self):
        def always_fail(conn_str, timeout):
            conn = _Conn(fail_next=1)
            self.made.append(conn)
            return conn
        client = ConnectClient(load_config(_ENV), connect_fn=always_fail, clock=self.clock)
        with self.assertRaises(RuntimeError):
            client.query("SELECT 1 FROM vendor")
        self.assertEqual(len(self.made), 2)

    def test_writes_never_reach_the_connection(self):
        with self.assertRaises(ReadOnlyError):
            self.client.query("DELETE FROM vendor")
        self.assertEqual(self.made, [])

    def test_an_idle_connection_is_replaced_before_the_next_query(self):
        # Prod 2026-10-28: a connection idle a few minutes was silently dropped
        # and the next query hung on it -- now it is never reused after 60s idle.
        self.client.query("SELECT 1 FROM vendor")
        self.clock.now += 59
        self.client.query("SELECT 1 FROM vendor")
        self.assertEqual(len(self.made), 1)
        self.clock.now += 60
        self.client.query("SELECT 1 FROM vendor")
        self.assertEqual(len(self.made), 2)
        self.assertTrue(self.made[0].closed)

    def test_close_closes_the_connection(self):
        self.client.query("SELECT 1 FROM vendor")
        self.client.close()
        self.assertTrue(self.made[0].closed)


class TimeoutTests(unittest.TestCase):
    """query(timeout=...): a hung query or a busy connection gives up in time
    (QueryTimeout), and the hung connection is not reused."""

    def setUp(self):
        self.made, self.release = [], threading.Event()
        self.hang_first = True

        def connect(conn_str, timeout):
            conn = _Conn(hang=self.release if (self.hang_first and not self.made) else None)
            self.made.append(conn)
            return conn

        self.client = ConnectClient(load_config(_ENV), connect_fn=connect)
        self.addCleanup(self.release.set)

    def test_a_hung_query_times_out_and_its_connection_is_dropped(self):
        started = time.monotonic()
        with self.assertRaises(QueryTimeout):
            self.client.query("SELECT 1 FROM vendor", timeout=0.3)
        self.assertLess(time.monotonic() - started, 2)
        # The next query gets a fresh connection, not the hung one.
        self.assertEqual(self.client.query("SELECT 1 FROM vendor", timeout=2), [{"id": 1, "tranid": "A1"}])
        self.assertEqual(len(self.made), 2)

    def test_a_query_waiting_behind_a_hung_one_gives_up_too(self):
        worker = threading.Thread(target=lambda: self.client.query("SELECT 1 FROM vendor"), daemon=True)
        worker.start()  # no timeout: holds the connection until released
        time.sleep(0.1)
        started = time.monotonic()
        with self.assertRaises(QueryTimeout):
            self.client.query("SELECT 2 FROM vendor", timeout=0.3)
        self.assertLess(time.monotonic() - started, 2)
        self.release.set()
        worker.join(2)

    def test_no_timeout_still_waits_for_slow_queries(self):
        # Matching passes no timeout: a slow (not dead) query still answers.
        threading.Timer(0.4, self.release.set).start()
        self.assertEqual(self.client.query("SELECT 1 FROM vendor"), [{"id": 1, "tranid": "A1"}])


if __name__ == "__main__":
    unittest.main()
