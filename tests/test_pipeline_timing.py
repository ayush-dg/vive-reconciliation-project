"""tests/test_pipeline_timing.py -- per-step timing lines, and saving them to job_step_timing behind a flag."""
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse import azure_sql_migrations as azure
from src.lakehouse import connection
from src.lakehouse.migrations import apply_pending_migrations
from src.pipeline_timing import parse_step_timings, save_job_timings, timing_log_enabled

OUTPUT = """
[Step 8] Uploading PDF to Blob Storage...
    Step timing: extraction=41.3s
    Step timing: validation=0.4s
    Step timing: intake_total=72.9s
  something else: matching=9s
    Step timing: matching=2.5s
    Step timing: netsuite_writeback=29.0s
    Step timing: not a number=abc
"""


class ParseStepTimingsTests(unittest.TestCase):
    def test_reads_only_well_formed_step_lines_in_order(self):
        self.assertEqual(parse_step_timings(OUTPUT), [
            ("extraction", 41.3), ("validation", 0.4), ("intake_total", 72.9),
            ("matching", 2.5), ("netsuite_writeback", 29.0)])

    def test_empty_or_missing_output(self):
        self.assertEqual(parse_step_timings(""), [])
        self.assertEqual(parse_step_timings(None), [])


class _TempDbCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="job_timing_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db = os.path.join(self.dir, "test.db")
        for patcher in (mock.patch.object(connection, "DB_PATH", self.db),
                        mock.patch.dict(os.environ, {"AZURE_SQL_SERVER": ""})):
            patcher.start()
            self.addCleanup(patcher.stop)
        conn = sqlite3.connect(self.db)
        apply_pending_migrations(conn)
        conn.close()

    def rows(self):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute("SELECT job_id, statement_id, pdf_filename, step, step_order, seconds "
                                "FROM job_step_timing ORDER BY id").fetchall()
        finally:
            conn.close()


class TheFlagTests(_TempDbCase):
    STEPS = [("extraction", 41.3), ("matching", 2.5)]

    def test_off_by_default_and_for_anything_but_true(self):
        for value in (None, "", "false", "1", "yes"):
            with self.subTest(value=value):
                env = {} if value is None else {"JOB_TIMING_LOG_ENABLED": value}
                with mock.patch.dict(os.environ, env):
                    if value is None:
                        os.environ.pop("JOB_TIMING_LOG_ENABLED", None)
                    self.assertFalse(timing_log_enabled())
                    self.assertEqual(save_job_timings("J1", "a.pdf", "STMT-1", self.STEPS), 0)
        self.assertEqual(self.rows(), [])

    def test_on_saves_one_row_per_step_in_order(self):
        with mock.patch.dict(os.environ, {"JOB_TIMING_LOG_ENABLED": "TRUE"}):
            self.assertEqual(save_job_timings("J1", "a.pdf", "STMT-1", self.STEPS), 2)
        self.assertEqual(self.rows(), [("J1", "STMT-1", "a.pdf", "extraction", 1, 41.3),
                                       ("J1", "STMT-1", "a.pdf", "matching", 2, 2.5)])

    def test_nothing_to_save_writes_nothing(self):
        with mock.patch.dict(os.environ, {"JOB_TIMING_LOG_ENABLED": "true"}):
            self.assertEqual(save_job_timings("J1", "a.pdf", None, []), 0)
        self.assertEqual(self.rows(), [])

    def test_a_database_problem_is_swallowed(self):
        with mock.patch.dict(os.environ, {"JOB_TIMING_LOG_ENABLED": "true"}), \
             mock.patch.object(connection, "_run_with_retry", side_effect=RuntimeError("db down")):
            self.assertEqual(save_job_timings("J1", "a.pdf", None, self.STEPS), 0)


class TheWorkerHookTests(_TempDbCase):
    def test_the_worker_saves_only_when_the_flag_is_on(self):
        from web import worker
        with mock.patch.dict(os.environ, {"JOB_TIMING_LOG_ENABLED": "false"}):
            worker._save_step_timings({"job_id": "J1", "pdf_filename": "a.pdf"}, OUTPUT, "STMT-9")
        self.assertEqual(self.rows(), [])
        with mock.patch.dict(os.environ, {"JOB_TIMING_LOG_ENABLED": "true"}):
            worker._save_step_timings({"job_id": "J1", "pdf_filename": "a.pdf"}, OUTPUT, "STMT-9")
            worker._save_step_timings({"job_id": "J2", "pdf_filename": "b.pdf"}, "no timing lines", "STMT-8")
        self.assertEqual([r[:4] for r in self.rows()][:2], [("J1", "STMT-9", "a.pdf", "extraction"),
                                                           ("J1", "STMT-9", "a.pdf", "validation")])
        self.assertEqual({r[0] for r in self.rows()}, {"J1"})


class SchemaParityTests(unittest.TestCase):
    def test_sqlite_and_azure_describe_the_same_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(os.path.join(tmp, "t.db"))
            apply_pending_migrations(conn)
            sqlite_cols = [row[1] for row in conn.execute("PRAGMA table_info(job_step_timing)")]
            conn.close()
        azure_cols = re.findall(r"^\s+(\w+)\s+(?:INT|NVARCHAR|FLOAT)", azure.TABLES["job_step_timing"], re.M)
        self.assertEqual(azure_cols, sqlite_cols)

    def test_it_comes_last_so_it_cannot_block_an_older_table(self):
        self.assertEqual(list(azure.TABLES)[-1], "job_step_timing")
        self.assertEqual(list(azure.INDEXES)[-1], "idx_job_step_timing_job")


if __name__ == "__main__":
    unittest.main()
