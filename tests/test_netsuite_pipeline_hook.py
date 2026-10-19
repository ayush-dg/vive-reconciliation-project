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
    def setUp(self):
        self.save_run = self._stub("save_run", return_value="run-1")
        self.save_failed_run = self._stub("save_failed_run", return_value="run-2")
        self._stub("write_error_log", return_value="err.json")

    def _stub(self, name, **kwargs):
        patcher = mock.patch.object(pipeline_hook, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

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

    def test_a_failed_run_returns_the_path_of_its_error_log(self):
        with mock.patch.dict(os.environ, {"NETSUITE_WRITEBACK_ENABLED": "true"}, clear=True):
            with mock.patch.object(pipeline_hook, "NetSuiteClient", return_value=mock.Mock()), \
                 mock.patch.object(pipeline_hook, "build_plans", side_effect=RuntimeError("boom")), \
                 mock.patch.object(pipeline_hook, "write_error_log", return_value="err.json") as err:
                result = pipeline_hook.run_netsuite_writeback("STMT-1")
        self.assertEqual(result["log"], "err.json")
        self.assertEqual(err.call_args.args[0], "STMT-1")

    def test_a_failed_run_is_also_saved_to_the_database(self):
        boom = RuntimeError("boom")
        with mock.patch.dict(os.environ, {"NETSUITE_WRITEBACK_ENABLED": "true"}, clear=True):
            with mock.patch.object(pipeline_hook, "NetSuiteClient", return_value=mock.Mock()), \
                 mock.patch.object(pipeline_hook, "build_plans", side_effect=boom):
                pipeline_hook.run_netsuite_writeback("STMT-1")
        args, kwargs = self.save_failed_run.call_args
        self.assertEqual((args[0], args[1]), ("STMT-1", boom))
        self.assertEqual(kwargs["log_path"], "err.json")
        self.assertIn("started_at", kwargs)

    def test_a_finished_run_is_saved_to_the_database(self):
        plans, results = [mock.Mock(action="PATCH_MATCHED")], [mock.Mock(ok=True, category="")]
        ns = mock.Mock(domain_id="7321761-sb1")
        with mock.patch.dict(os.environ, {"NETSUITE_WRITEBACK_ENABLED": "true"}, clear=True):
            with mock.patch.object(pipeline_hook, "NetSuiteClient", return_value=ns), \
                 mock.patch.object(pipeline_hook, "build_plans", return_value=(mock.Mock(), plans)), \
                 mock.patch.object(pipeline_hook, "apply_plans", return_value=results), \
                 mock.patch.object(pipeline_hook, "write_apply_log", return_value="log.json"):
                pipeline_hook.run_netsuite_writeback("STMT-1")
        args, kwargs = self.save_run.call_args
        self.assertEqual(args, ("STMT-1", results, plans))
        self.assertEqual((kwargs["sandbox"], kwargs["log_path"]), ("7321761-sb1", "log.json"))
        self.assertIn("started_at", kwargs)

    def test_nothing_is_saved_when_the_write_back_is_off(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            pipeline_hook.run_netsuite_writeback("STMT-1")
        self.save_run.assert_not_called()
        self.save_failed_run.assert_not_called()

    def test_summary_counts_written_failed_period_locked_and_not_written(self):
        from src.netsuite.writeback import ApplyResult
        plans = [mock.Mock(action="PATCH_MATCHED"), mock.Mock(action="SKIP_REVIEW")]
        results = [
            ApplyResult(mock.Mock(), True, "updated"),
            ApplyResult(mock.Mock(), False, "boom", category="failed"),
            ApplyResult(mock.Mock(), False, "locked", category="period locked"),
            ApplyResult(mock.Mock(), False, "locked", category="period locked"),
            ApplyResult(mock.Mock(), False, "raced", category="reconciled by another statement"),
        ]
        with mock.patch.dict(os.environ, {"NETSUITE_WRITEBACK_ENABLED": "true"}, clear=True):
            with mock.patch.object(pipeline_hook, "NetSuiteClient", return_value=mock.Mock()), \
                 mock.patch.object(pipeline_hook, "build_plans", return_value=(mock.Mock(), plans)), \
                 mock.patch.object(pipeline_hook, "apply_plans", return_value=results), \
                 mock.patch.object(pipeline_hook, "skip_counts", return_value={"not in sandbox": 1}), \
                 mock.patch.object(pipeline_hook, "write_apply_log", return_value="log.json") as log:
                result = pipeline_hook.run_netsuite_writeback("STMT-1")
        self.assertEqual(result, {"written": 1, "failed": 1, "period_locked": 2, "held_by_other": 1,
                                  "links_added": 0, "link_only_failed": 0, "link_mismatch": 0,
                                  "not_written": {"not in sandbox": 1}, "log": "log.json"})
        # The log is given the plans too, so skipped lines are recorded.
        self.assertIs(log.call_args.args[3], plans)


if __name__ == "__main__":
    unittest.main()
