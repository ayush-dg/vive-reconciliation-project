"""
tests/test_failure_reasons.py

Every job that ends as an extraction failure carries a specific, plain reason as the LAST line of its
error_message -- the line the dashboard shows (web/deps.py friendly_error(), Home "Failed" tab, the
statement processing page) -- never just the last line of whatever the pipeline happened to print
(2026-10-26):

  No rows: ...           the extraction stored a statement with no line items
  Pipeline error: ...    the pipeline raised (the exception's own line)
  PDF not found: ...     the PDF was gone from the worker
  No statement: ...      the pipeline ended without a statement id
  Pipeline stopped: ...  any other non-zero exit
  Timed out / Stalled host: ...  the 30-minute cap / a dead host (tests/test_job_recovery.py)

The reasons already written that way are unchanged: not a statement, the Silver field-mapping check,
and (with restart recovery off) the timeout's "Worker error: ... timed out ..." line. Stand-in pipeline
results only.
"""

import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.pipeline_markers import NOT_A_STATEMENT_MARKER, SILVER_CHECK_MARKER
from web import worker
from web.deps import friendly_error

BANNER = "#" * 60 + "\n  FULL RECONCILIATION PIPELINE\n" + "#" * 60 + "\n"


class _Case(unittest.TestCase):

    def run_job(self, stdout, returncode=0, silver_rows=0, stderr=""):
        job = {"job_id": "J1", "pdf_path": __file__, "pdf_filename": "x.pdf", "source_blob_path": None}
        completed = subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)
        with mock.patch("web.worker.subprocess.run", return_value=completed), \
                mock.patch("web.queries.get_silver_row_count", return_value=silver_rows), \
                mock.patch("web.queries.get_vendor_name_for_statement", return_value="V"), \
                mock.patch.object(worker, "_write_blob_outcome"), mock.patch("builtins.print"), \
                mock.patch("web.queries.update_job_status") as update:
            worker._run_job(job)
        kwargs = update.call_args.kwargs
        self.assertEqual(kwargs["status"], "FAILED")
        return kwargs["error_message"], friendly_error(kwargs["error_message"])


class TestSpecificReasons(_Case):

    def test_no_rows(self):
        message, shown = self.run_job(BANNER + "Statement ID: STMT-1\nPIPELINE STOPPED\n", silver_rows=0)
        self.assertTrue(message.startswith("Extraction completed but produced 0 rows"))   # unchanged start
        self.assertEqual(shown, "No rows: the extraction stored no line items for statement_id STMT-1.")

    def test_a_raised_exception(self):
        out = BANNER + "Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: could not convert 'n/a'\n"
        _, shown = self.run_job(out, returncode=1)
        self.assertEqual(shown, "Pipeline error: ValueError: could not convert 'n/a'")

    def test_pdf_not_found(self):
        out = BANNER + "Traceback (most recent call last):\nFileNotFoundError: PDF not found: sample_data/a/x.pdf\n"
        _, shown = self.run_job(out, returncode=1)
        self.assertTrue(shown.startswith("PDF not found:"), shown)

    def test_no_statement_id(self):
        _, shown = self.run_job(BANNER + "  [Engine] Falling back to pdfplumber (deterministic)...\n", returncode=0)
        self.assertTrue(shown.startswith("No statement:"), shown)

    def test_any_other_non_zero_exit(self):
        _, shown = self.run_job(BANNER + "  Step timing: ai_call=12.0s\n", returncode=3)
        self.assertTrue(shown.startswith("Pipeline stopped (exit 3):"), shown)

    def test_no_output_at_all(self):
        _, shown = self.run_job("", returncode=1)
        self.assertTrue(shown.startswith("Pipeline stopped (exit 1):"), shown)


class TestReasonsAlreadyPlainAreUnchanged(_Case):

    def test_not_a_statement(self):
        out = f"Statement ID: STMT-1\n  {NOT_A_STATEMENT_MARKER} no line-item table found\nPIPELINE STOPPED"
        _, shown = self.run_job(out, silver_rows=0)
        self.assertTrue(shown.startswith(NOT_A_STATEMENT_MARKER))

    def test_silver_field_mapping(self):
        out = f"Statement ID: STMT-X\n{SILVER_CHECK_MARKER} No lines read: 3 lines matched no field mapping (statement_id STMT-X)\n"
        _, shown = self.run_job(out, returncode=3, stderr="DeprecationWarning: noisy\n")
        self.assertEqual(shown, "No lines read: 3 lines matched no field mapping (statement_id STMT-X)")

    def test_the_timeout_line_without_restart_recovery(self):
        job = {"job_id": "J1", "pdf_path": __file__, "pdf_filename": "x.pdf", "source_blob_path": None}
        error = subprocess.TimeoutExpired(cmd=["pipeline"], timeout=1800, output=b"Step timing: ai_call=300.0s", stderr=b"")
        with mock.patch("web.worker.subprocess.run", side_effect=error), mock.patch.object(worker, "_write_blob_outcome"), \
                mock.patch("builtins.print"), mock.patch("web.queries.update_job_status") as update:
            worker._run_job(job)
        self.assertEqual(friendly_error(update.call_args.kwargs["error_message"]),
                         "Worker error: Command '['pipeline']' timed out after 1800 seconds")


if __name__ == "__main__":
    unittest.main()
