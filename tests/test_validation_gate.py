"""
tests/test_validation_gate.py

Only a statement that passes the Arithmetic Validation Gate 100% ("matches")
goes on to Silver + reconciliation (src/validation/gate.py). Every other
result stops scripts/run_full_pipeline.py right after intake -- a normal exit
printing VALIDATION_GATE_MARKER -- and web/worker.py marks the job COMPLETED
with a "Not reconciled -- <reason>" note, not FAILED (failed jobs are for
failed extractions). VALIDATION_GATE_ENABLED=false turns the gate off.
"""

import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.pipeline_markers import VALIDATION_GATE_MARKER
from src.validation.gate import describe_failure, gate_enabled


class TestDescribeFailure(unittest.TestCase):

    def test_only_matches_passes(self):
        self.assertIsNone(describe_failure({"status": "matches", "difference": 0.0}))

    def test_mismatch_names_both_totals(self):
        msg = describe_failure({"status": "mismatch", "printed": 1373.0, "computed": 1150.48, "difference": 222.52})
        self.assertEqual(msg, "Validation failed: printed total $1,373.00, extracted lines sum to $1,150.48 (off by $222.52)")

    def test_mismatch_without_totals_still_says_by_how_much(self):
        # A cache hit carries only status/difference from the original intake row.
        self.assertEqual(describe_failure({"status": "mismatch", "difference": -5495.44}),
                         "Validation failed: off by $-5,495.44")

    def test_total_not_found_no_line_items_and_missing_all_fail(self):
        self.assertIn("no printed statement total", describe_failure({"status": "total_not_found"}))
        self.assertIn("no line items", describe_failure({"status": "no_line_items"}))
        self.assertIn("no validation result", describe_failure({}))
        self.assertIn("no validation result", describe_failure(None))


class TestGateEnabled(unittest.TestCase):

    def test_on_unless_set_to_false(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VALIDATION_GATE_ENABLED", None)
            self.assertTrue(gate_enabled())
        for value, on in (("true", True), ("TRUE", True), ("false", False), (" False ", False)):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"VALIDATION_GATE_ENABLED": value}):
                self.assertEqual(gate_enabled(), on)


class _StopAfterSilver(Exception):
    pass


class TestPipelineStopsBeforeSilver(unittest.TestCase):

    def _run(self, validation, env=None):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        import run_full_pipeline as rfp
        intake = mock.Mock()
        intake.run_intake.return_value = {"statement_id": "STMT-X", "bronze_count": 3, "validation": validation}
        build = mock.Mock(side_effect=_StopAfterSilver)
        with mock.patch.object(rfp, "load_notebook", return_value=intake), \
                mock.patch.object(sys, "argv", ["run_full_pipeline.py", "--pdf", "x.pdf"]), \
                mock.patch.dict(os.environ, {"RESEARCH_MODE_EXTRACTION_ONLY": "false", **(env or {})}), \
                mock.patch("src.lakehouse.silver_build.build_silver_direct", build), \
                mock.patch("src.lakehouse.silver_build.silver_build_mode", return_value="direct"):
            try:
                rfp.main()
            except SystemExit as e:
                return ("exit", e.code), build
            except _StopAfterSilver:
                return "silver", build
        return "stopped", build

    def test_mismatch_stops_normally_without_building_silver(self):
        with mock.patch("builtins.print") as printed:
            outcome, build = self._run({"status": "mismatch", "printed": 10.0, "computed": 9.0, "difference": 1.0})
        self.assertEqual(outcome, "stopped")
        build.assert_not_called()
        lines = [" ".join(str(a) for a in c.args) for c in printed.call_args_list]
        self.assertIn(f"{VALIDATION_GATE_MARKER} Validation failed: printed total $10.00, extracted lines sum to "
                      f"$9.00 (off by $1.00) (statement_id STMT-X)", lines)

    def test_total_not_found_is_stopped_too(self):
        with mock.patch("builtins.print"):
            outcome, build = self._run({"status": "total_not_found"})
        self.assertEqual(outcome, "stopped")
        build.assert_not_called()

    def test_matches_goes_on_to_silver(self):
        with mock.patch("builtins.print"):
            outcome, build = self._run({"status": "matches", "difference": 0.0})
        self.assertEqual(outcome, "silver")
        build.assert_called_once_with("STMT-X")

    def test_gate_off_lets_a_mismatch_through(self):
        with mock.patch("builtins.print"):
            outcome, build = self._run({"status": "mismatch", "difference": 1.0}, env={"VALIDATION_GATE_ENABLED": "false"})
        self.assertEqual(outcome, "silver")


class TestWorkerMarksItCompleted(unittest.TestCase):

    PROBLEM = "Validation failed: printed total $10.00, extracted lines sum to $9.00 (off by $1.00)"

    def _run_job(self, silver_rows):
        from web import worker
        stdout = f"Statement ID: STMT-X\n{VALIDATION_GATE_MARKER} {self.PROBLEM} (statement_id STMT-X)\n"
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
        job = {"job_id": "J1", "pdf_path": __file__, "pdf_filename": "x.pdf", "source_blob_path": "raw/x.pdf"}
        with mock.patch("web.worker.subprocess.run", return_value=completed), \
                mock.patch("web.queries.get_silver_row_count", return_value=silver_rows), \
                mock.patch("web.queries.get_vendor_name_for_statement", return_value="Acme"), \
                mock.patch("web.worker._write_blob_outcome") as outcome, \
                mock.patch("web.queries.update_job_status") as update:
            worker._run_job(job)
        return update.call_args.kwargs, outcome.call_args.args

    def test_stopped_at_validation_is_completed_with_the_reason_as_note(self):
        kwargs, outcome = self._run_job(silver_rows=12)
        self.assertEqual(kwargs["status"], "COMPLETED")
        self.assertEqual(kwargs["statement_id"], "STMT-X")
        self.assertEqual(kwargs["error_message"], f"Not reconciled -- {self.PROBLEM} (statement_id STMT-X)")
        # Mailbox blob marked completed, so the sync doesn't retry it.
        self.assertEqual(outcome[1], "completed")

    def test_nothing_extracted_is_still_a_failed_job(self):
        kwargs, _ = self._run_job(silver_rows=0)
        self.assertEqual(kwargs["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
