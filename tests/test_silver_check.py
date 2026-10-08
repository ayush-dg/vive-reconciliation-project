"""
tests/test_silver_check.py

src/lakehouse/silver_check.py fails a job whose lines didn't come through
the field mapping (added 2026-10-08, after prod STMT-3C9D4BBB Fred Beans and
STMT-EC5E296A Astech showed 0 / 0 / 0), and web/worker.py shows the problem
as the job's final message. No Fabric or SQL access: connections, the
subprocess and job-status writes are mocked.
"""

import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse import silver_check
from src.lakehouse.silver_check import describe_problem
from src.pipeline_markers import SILVER_CHECK_MARKER


class TestDescribeProblem(unittest.TestCase):

    def test_no_silver_lines_with_bronze_lines(self):
        self.assertTrue(describe_problem(0, 0, 0, 135).startswith("No lines read: 135 lines were extracted"))

    def test_no_lines_anywhere_is_not_this_checks_problem(self):
        self.assertIsNone(describe_problem(0, 0, 0, 0))

    def test_no_invoice_numbers_or_no_amounts_fails_any_size(self):
        self.assertTrue(describe_problem(2, 0, 0, 2).startswith("Field mapping incomplete"))
        self.assertTrue(describe_problem(3, 3, 0, 3).startswith("Field mapping incomplete"))
        self.assertTrue(describe_problem(3, 0, 3, 3).startswith("Field mapping incomplete"))

    def test_small_statement_may_have_a_row_without_invoice(self):
        # e.g. dev Goyette's STMT-7DF58A05: 3 lines, 1 with an invoice number
        self.assertIsNone(describe_problem(3, 1, 3, 3))

    def test_large_statement_needs_half_with_invoice_and_amount(self):
        self.assertTrue(describe_problem(10, 4, 10, 10).startswith("Field mapping incomplete"))
        self.assertTrue(describe_problem(10, 10, 4, 10).startswith("Field mapping incomplete"))
        self.assertIsNone(describe_problem(10, 5, 5, 10))
        # e.g. dev Mastria STMT-53072C69: 134 lines, 87 with an amount
        self.assertIsNone(describe_problem(134, 134, 87, 134))


class _Cursor:
    def __init__(self, results):
        self.results = list(results)

    def execute(self, sql, params=None):
        self.current = self.results.pop(0)

    def fetchone(self):
        return self.current[0] if self.current else None

    def fetchall(self):
        return self.current


class _Conn:
    def __init__(self, results):
        self._cursor = _Cursor(results)

    def cursor(self):
        return self._cursor


class TestCheckSilverLines(unittest.TestCase):

    def _check(self, wh_results, lh_results):
        wh, lh = _Conn(wh_results), _Conn(lh_results)
        with mock.patch("src.lakehouse.fabric_sql.get_warehouse_connection", return_value=wh), \
             mock.patch("src.lakehouse.fabric_sql.get_lakehouse_connection", return_value=lh):
            return silver_check.check_silver_lines("STMT-X")

    def test_zero_lines_names_vendor_and_unmapped_fields(self):
        problem = self._check(
            [[("ASTECH",)], [(0, None, None)]],
            [[(135,)], [("Invoice #",), ("Outstanding Amount",), ("confidence",), ("invoice_no",)]],
        )
        self.assertTrue(problem.startswith("No lines read: 135 lines were extracted but none matched ASTECH's field mapping"))
        self.assertIn("Unmapped fields: 'Invoice #', 'Outstanding Amount'", problem)
        self.assertNotIn("confidence", problem)
        self.assertNotIn("'invoice_no'", problem)

    def test_healthy_statement_passes(self):
        self.assertIsNone(self._check([[("ASTECH",)], [(135, 135, 135)]], []))

    def test_errors_never_fail_the_job(self):
        with mock.patch("src.lakehouse.fabric_sql.get_warehouse_connection", side_effect=RuntimeError("down")):
            self.assertIsNone(silver_check.check_silver_lines("STMT-X"))


class TestWorkerMessage(unittest.TestCase):

    def test_silver_check_problem_is_the_jobs_final_line(self):
        from web import worker
        problem = "No lines read: 135 lines were extracted but none matched ASTECH's field mapping"
        stdout = f"Statement ID: STMT-X\n    Fabric Silver build: OK\n{SILVER_CHECK_MARKER} {problem} (statement_id STMT-X)\n"
        completed = subprocess.CompletedProcess(args=[], returncode=3, stdout=stdout,
                                                stderr="DeprecationWarning: something noisy\n")
        job = {"job_id": "J1", "pdf_path": __file__, "pdf_filename": "x.pdf", "source_blob_path": None}
        with mock.patch("web.worker.subprocess.run", return_value=completed), \
             mock.patch("web.queries.update_job_status") as update:
            worker._run_job(job)
        kwargs = update.call_args.kwargs
        self.assertEqual(kwargs["status"], "FAILED")
        self.assertEqual(kwargs["error_message"].strip().splitlines()[-1], f"{problem} (statement_id STMT-X)")


if __name__ == "__main__":
    unittest.main()
