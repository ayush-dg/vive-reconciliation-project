"""
tests/test_outlook_freshness.py

Home's "Outlook" badge (2026-11-13): when the newest PDF arrived from the
mailbox -- the newest job queued from mailbox storage (source_blob_path set).
It used to read the old mailbox-sync Function's watermark file, which has not
changed since that Function was switched off on 2026-10-20.
"""

import os
import sqlite3
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web import queries


class OutlookFreshnessTests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE jobs (job_id TEXT, submitted_at TEXT, source_blob_path TEXT)")
        patcher = mock.patch.object(queries, "execute_query",
                                    lambda sql, params=None: [dict(r) for r in self.db.execute(sql, params or [])])
        patcher.start()
        self.addCleanup(patcher.stop)

    def _job(self, when, blob):
        self.db.execute("INSERT INTO jobs VALUES (?, ?, ?)", ["j", when, blob])

    def test_newest_mailbox_job_wins_and_uploads_do_not_count(self):
        self._job("2026-11-12T11:58:00", "mailbox/2026/11/12/raw_statement/a.pdf")
        self._job("2026-11-10T09:00:00", "mailbox/2026/11/10/raw_statement/b.pdf")
        self._job("2026-11-13T08:00:00", None)  # a manual upload
        self.assertEqual(queries.get_last_outlook_sync(), "2026-11-12T11:58:00")

    def test_no_mailbox_jobs_means_never_synced(self):
        self._job("2026-11-13T08:00:00", None)
        self.assertIsNone(queries.get_last_outlook_sync())

    def test_a_database_problem_never_breaks_home(self):
        with mock.patch.object(queries, "execute_query", side_effect=RuntimeError("down")):
            self.assertIsNone(queries.get_last_outlook_sync())


if __name__ == "__main__":
    unittest.main()
