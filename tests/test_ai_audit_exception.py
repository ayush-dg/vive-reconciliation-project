"""
tests/test_ai_audit_exception.py

An AI call that raises instead of returning a response gets an ai_audit_log
row (2026-10-25): on dev, Receipts 47 2 fell back to pdfplumber with no
DOCUMENT_UNDERSTANDING row at all, so nothing showed why the AI path failed.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ai import audit_logger
from src.ai import document_understanding_engine as due
from src.ai.base_client import AIResponse


class FakeClaudeSonnetClient:
    model = "claude-sonnet-test"

    def __init__(self, error=None, response=None):
        self.error, self.response = error, response

    def generate_with_file(self, path, prompt):
        if self.error:
            raise self.error
        return self.response


FakeClaudeSonnetClient.__name__ = "ClaudeSonnetClient"


class TestAuditRowForAnAiCallThatRaises(unittest.TestCase):

    def _understand(self, client, log=None):
        fallback = {"invoices": [{"invoice_number": "17"}]}
        patches = [mock.patch.object(due.client_factory, "get_ai_client", return_value=client),
                   mock.patch.object(due, "upright_copy", side_effect=lambda p: (p, {})),
                   mock.patch.object(due, "extract_with_pdfplumber", return_value=dict(fallback)),
                   mock.patch("builtins.print")]
        if log is not None:
            patches.append(mock.patch.object(due, "log_ai_call", log))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return due.DocumentUnderstandingEngine().understand("", "receipts 47-2.pdf", statement_id="STMT-T1")

    def test_exception_is_logged_as_a_failed_call_then_falls_back(self):
        log = mock.Mock()
        result = self._understand(FakeClaudeSonnetClient(error=RuntimeError("Response ended prematurely")), log)
        self.assertEqual(result["_provider_used"], "pdfplumber")       # the fallback still runs
        log.assert_called_once()
        response, kwargs = log.call_args.args[0], log.call_args.kwargs
        self.assertFalse(response.success)
        self.assertEqual((response.provider, response.model), ("claude_sonnet", "claude-sonnet-test"))
        self.assertEqual(response.error, "RuntimeError: Response ended prematurely")
        self.assertGreaterEqual(response.latency_ms, 0)
        self.assertEqual(kwargs, {"interaction_type": "DOCUMENT_UNDERSTANDING", "prompt_version": "vision_v1",
                                  "source_file": "receipts 47-2.pdf", "statement_id": "STMT-T1",
                                  "validation_result": "ERROR"})

    def test_the_row_written_records_status_and_message(self):
        with mock.patch.object(audit_logger, "execute_sql") as sql:
            self._understand(FakeClaudeSonnetClient(error=TimeoutError("The read operation timed out")))
        params = sql.call_args.args[1]
        # audit_id, source_file, vendor_id, statement_id, interaction_type, provider, model, prompt_version,
        # request_timestamp, latency_ms, attempt_count, success, response_status, error_message, confidence, result
        self.assertEqual(params[1], "receipts 47-2.pdf")
        self.assertEqual(params[3:6], ["STMT-T1", "DOCUMENT_UNDERSTANDING", "claude_sonnet"])
        self.assertEqual(params[11:14], [0, "TRANSPORT_ERROR", "TimeoutError: The read operation timed out"])
        self.assertEqual(params[15], "ERROR")

    def test_a_returned_failure_is_logged_as_before(self):
        log = mock.Mock()
        self._understand(FakeClaudeSonnetClient(response=AIResponse(success=False, error="HTTP 529 overloaded",
                                                                    provider="claude_sonnet")), log)
        log.assert_called_once()
        self.assertEqual(log.call_args.kwargs["validation_result"], "FAILED")

    def test_an_audit_write_failure_never_stops_the_extraction(self):
        log = mock.Mock(side_effect=RuntimeError("db down"))
        result = self._understand(FakeClaudeSonnetClient(error=RuntimeError("boom")), log)
        self.assertEqual(result["_provider_used"], "pdfplumber")


if __name__ == "__main__":
    unittest.main()
