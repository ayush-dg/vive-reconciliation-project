"""
tests/test_netsuite_pipeline_hook.py

Offline tests for src/netsuite/pipeline_hook.py: it must be off by default
and must never raise into the pipeline. No NetSuite calls are made.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.netsuite import pipeline_hook
from src.netsuite.client import NetSuiteConfigError


class PipelineHookTests(unittest.TestCase):
    def test_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = pipeline_hook.run_netsuite_writeback("STMT-1")
        self.assertTrue(result["skipped"])

    def test_only_the_literal_true_switches_it_on(self):
        for value in ("false", "0", "yes", ""):
            with self.subTest(value=value), mock.patch.dict(
                    os.environ, {"NETSUITE_WRITEBACK_ENABLED": value}, clear=True):
                self.assertTrue(pipeline_hook.run_netsuite_writeback("STMT-1")["skipped"])

    def test_missing_credentials_are_skipped_not_raised(self):
        with mock.patch.dict(os.environ, {"NETSUITE_WRITEBACK_ENABLED": "true"}, clear=True):
            with mock.patch.object(pipeline_hook, "NetSuiteClient",
                                   side_effect=NetSuiteConfigError("Missing env var(s): X")):
                result = pipeline_hook.run_netsuite_writeback("STMT-1")
        self.assertTrue(result["skipped"])
        self.assertIn("Missing env var", result["reason"])

    def test_any_other_failure_is_returned_not_raised(self):
        with mock.patch.dict(os.environ, {"NETSUITE_WRITEBACK_ENABLED": "true"}, clear=True):
            with mock.patch.object(pipeline_hook, "NetSuiteClient", return_value=mock.Mock()), \
                 mock.patch.object(pipeline_hook, "build_plans", side_effect=RuntimeError("boom")):
                result = pipeline_hook.run_netsuite_writeback("STMT-1")
        self.assertIn("boom", result["error"])

    def test_summary_counts_written_failed_period_locked_and_not_written(self):
        from src.netsuite.writeback import ApplyResult
        plans = [mock.Mock(action="PATCH_MATCHED"), mock.Mock(action="SKIP_REVIEW")]
        results = [
            ApplyResult(mock.Mock(), True, "updated"),
            ApplyResult(mock.Mock(), False, "boom", category="failed"),
            ApplyResult(mock.Mock(), False, "locked", category="period locked"),
            ApplyResult(mock.Mock(), False, "locked", category="period locked"),
        ]
        with mock.patch.dict(os.environ, {"NETSUITE_WRITEBACK_ENABLED": "true"}, clear=True):
            with mock.patch.object(pipeline_hook, "NetSuiteClient", return_value=mock.Mock()), \
                 mock.patch.object(pipeline_hook, "build_plans", return_value=(mock.Mock(), plans)), \
                 mock.patch.object(pipeline_hook, "apply_plans", return_value=results), \
                 mock.patch.object(pipeline_hook, "skip_counts", return_value={"not in sandbox": 1}), \
                 mock.patch.object(pipeline_hook, "write_apply_log", return_value="log.json") as log:
                result = pipeline_hook.run_netsuite_writeback("STMT-1")
        self.assertEqual(result, {"written": 1, "failed": 1, "period_locked": 2,
                                  "not_written": {"not in sandbox": 1}, "log": "log.json"})
        # The log is given the plans too, so skipped lines are recorded.
        self.assertIs(log.call_args.args[3], plans)


if __name__ == "__main__":
    unittest.main()
