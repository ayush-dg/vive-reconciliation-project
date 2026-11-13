"""
tests/test_connect_helper.py

The web app's live NetSuite helper process (2026-11-13,
src/netsuite/connect_helper.py), run for real -- a spawned process with a
fake backend (tests/fake_connect_backend.py) instead of the NetSuite driver:
- queries run in the helper, side by side on its pool;
- a hanging query: the caller gets a timeout, the helper is restarted once
  every connection is stuck, and the next query works;
- a crash in the helper (exit 139): waiting callers fail at once, the web side
  is unaffected, and the next query starts a new helper;
- a full pool answers "busy" quickly instead of queueing;
- only SELECTs are sent.
"""

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from src.netsuite import connect_client, connect_helper
from src.netsuite.connect_client import QueryTimeout, ReadOnlyError

FAKE = "fake_connect_backend:make_client"


class ConnectHelperTests(unittest.TestCase):

    def _helper(self, size=2, max_wait=3.0):
        helper = connect_helper.ConnectHelper(size=size, max_wait=max_wait, odbc_timeout=45, factory_path=FAKE)
        self.addCleanup(helper.stop)
        return helper

    def test_queries_run_in_the_helper_process_with_the_driver_timeout(self):
        helper = self._helper()
        rows = helper.query("SELECT 1 FROM vendor WHERE id = ?", [7], timeout=20)
        self.assertNotEqual(rows[0]["pid"], os.getpid())
        self.assertEqual((rows[0]["params"], rows[0]["odbc_timeout"]), ([7], 45))

    def test_the_pool_runs_queries_side_by_side(self):
        helper = self._helper(size=3)
        helper.query("SELECT 'warm'", timeout=20)  # start the process first
        started = time.monotonic()
        threads = [threading.Thread(target=helper.query, args=("SELECT 'slow'",), kwargs={"timeout": 20})
                   for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertLess(time.monotonic() - started, 3.5)  # 3 x 1.5 s in parallel, not 4.5 s in a row

    def test_a_full_pool_answers_busy_quickly(self):
        helper = self._helper(size=1, max_wait=0.3)
        helper.query("SELECT 'warm'", timeout=20)
        slow = threading.Thread(target=helper.query, args=("SELECT 'slow'",), kwargs={"timeout": 20})
        slow.start()
        time.sleep(0.2)
        started = time.monotonic()
        with self.assertRaises(connect_helper.HelperBusy):
            helper.query("SELECT 'next'", timeout=20)
        self.assertLess(time.monotonic() - started, 1.2)  # the queue wait, not the slow query
        slow.join()
        self.assertTrue(helper.query("SELECT 'free again'", timeout=20))

    def test_a_hanging_query_times_out_and_the_stuck_helper_is_replaced(self):
        helper = self._helper(size=2)
        helper.query("SELECT 'warm'", timeout=20)
        for _ in range(2):  # both connections stuck
            with self.assertRaises(QueryTimeout):
                helper.query("SELECT 'hang'", timeout=0.5)
        self.assertEqual(helper.restarts, 1)
        rows = helper.query("SELECT 'after'", timeout=20)  # a new helper answers
        self.assertTrue(rows)

    def test_a_crash_fails_waiting_callers_at_once_and_the_next_query_works(self):
        helper = self._helper(size=2)
        first_pid = helper.query("SELECT 'warm'", timeout=20)[0]["pid"]
        started = time.monotonic()
        with self.assertRaises(connect_helper.HelperUnavailable):
            helper.query("SELECT 'crash'", timeout=30)
        self.assertLess(time.monotonic() - started, 10)  # not the full 30 s
        rows = helper.query("SELECT 'after'", timeout=20)
        self.assertNotEqual(rows[0]["pid"], first_pid)
        self.assertEqual(helper.restarts, 1)

    def test_connections_log_in_at_start_and_idle_ones_are_kept_alive(self):
        helper = connect_helper.ConnectHelper(size=2, max_wait=3.0, odbc_timeout=45, factory_path=FAKE, keepalive=0.3)
        self.addCleanup(helper.stop)
        helper.warm_up()
        time.sleep(0.5)
        at_start = helper.query("SELECT 'pings'", timeout=20)[0]["pings"]
        self.assertGreaterEqual(at_start, 2)  # each connection logged in before any search
        time.sleep(1.5)
        self.assertGreater(helper.query("SELECT 'pings'", timeout=20)[0]["pings"], at_start + 2)

    def test_only_selects_are_sent(self):
        helper = self._helper()
        with self.assertRaises(ReadOnlyError):
            helper.query("DELETE FROM transaction", timeout=5)


class SwitchTests(unittest.TestCase):

    def tearDown(self):
        connect_client.use_helper(False)
        connect_helper.stop_helper()

    def test_off_by_default_so_pipeline_processes_keep_their_own_client(self):
        # A fresh process -- as each pipeline job is -- starts with it off.
        import subprocess
        root = os.path.join(os.path.dirname(__file__), "..")
        out = subprocess.run([sys.executable, "-c", "from src.netsuite import connect_client as c; print(c._use_helper)"],
                             cwd=root, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip(), "False")

    def test_on_the_web_app_gets_the_helper(self):
        connect_client.use_helper(True)
        self.assertIsInstance(connect_client.get_shared_client(), connect_helper.ConnectHelper)
        self.assertIs(connect_client.get_shared_client(), connect_client.get_shared_client())


if __name__ == "__main__":
    unittest.main()
