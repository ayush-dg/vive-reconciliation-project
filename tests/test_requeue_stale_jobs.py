"""
tests/test_requeue_stale_jobs.py

queries.requeue_stale_processing_jobs() puts jobs left PROCESSING by a dead
container back to PENDING (added 2026-10-13), but only once they're older
than the worker's 30-minute pipeline cap, so a job the previous container is
still finishing during a deploy swap is untouched. Runs against an in-memory
SQLite jobs table.
"""

import os
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web import queries


class TestRequeueStaleJobs(unittest.TestCase):

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE jobs (job_id TEXT, status TEXT, started_at TEXT, claim_token TEXT)")
        now = datetime.now(timezone.utc)
        for jid, status, age in (("old", "PROCESSING", 120), ("fresh", "PROCESSING", 10),
                                 ("done", "COMPLETED", 120), ("queued", "PENDING", None)):
            started = (now - timedelta(minutes=age)).isoformat() if age is not None else None
            self.conn.execute("INSERT INTO jobs VALUES (?, ?, ?, ?)", [jid, status, started, "tok-" + jid])
        q = lambda sql, p=None: [dict(r) for r in self.conn.execute(sql, p or []).fetchall()]
        x = lambda sql, p=None: self.conn.execute(sql, p or [])
        for name, fn in (("execute_query", q), ("execute_sql", x)):
            patcher = mock.patch.object(queries, name, fn)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _status(self):
        return {r["job_id"]: (r["status"], r["started_at"] is None, r["claim_token"]) for r in
                (dict(x) for x in self.conn.execute("SELECT * FROM jobs").fetchall())}

    def test_only_old_processing_jobs_are_requeued(self):
        self.assertEqual(queries.requeue_stale_processing_jobs(), 1)
        s = self._status()
        self.assertEqual(s["old"], ("PENDING", True, None))
        self.assertEqual(s["fresh"][0], "PROCESSING")
        self.assertEqual(s["done"][0], "COMPLETED")
        self.assertEqual(s["queued"][0], "PENDING")

    def test_nothing_stale_is_a_no_op(self):
        queries.requeue_stale_processing_jobs()
        self.assertEqual(queries.requeue_stale_processing_jobs(), 0)


if __name__ == "__main__":
    unittest.main()
