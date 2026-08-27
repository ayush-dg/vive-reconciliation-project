"""
tests/test_ai_clients.py

Tests for ClaudeClient using injected fake transports.
No real API calls made — tests run fully offline.
"""

import os
import sys
import unittest

# Make src importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["ANTHROPIC_API_KEY"] = "test-claude-key"

from src.ai.claude_client import ClaudeClient

CLAUDE_CONFIG = {
    "provider": "claude",
    "model": "claude-haiku-4-5-20251001",
    "api_key_env_var": "ANTHROPIC_API_KEY",
    "temperature": 0.1,
    "max_output_tokens": 8192,
    "timeout_seconds": 30,
    "retry_policy": {"max_retries": 1, "backoff_seconds": 0, "backoff_multiplier": 1},
}


class TestClaudeClient(unittest.TestCase):

    def test_successful_response_parses_json(self):
        def fake_transport(prompt, config):
            return True, '{"invoices": [], "document_metadata": {"document_type": "VENDOR_STATEMENT"}}', None

        client = ClaudeClient(CLAUDE_CONFIG, transport=fake_transport)
        response = client.generate("extract this")

        self.assertTrue(response.success)
        self.assertIsNotNone(response.parsed_json)
        self.assertEqual(response.provider, "claude")

    def test_missing_api_key_fails_cleanly(self):
        config = dict(CLAUDE_CONFIG, api_key_env_var="DEFINITELY_NOT_SET_XYZ")
        client = ClaudeClient(config, transport=None)
        response = client.generate("test")

        self.assertFalse(response.success)
        self.assertIn("DEFINITELY_NOT_SET_XYZ", response.error)

    def test_retries_on_failure_then_succeeds(self):
        attempts = {"count": 0}

        def flaky_transport(prompt, config):
            attempts["count"] += 1
            if attempts["count"] < 2:
                return False, "", "temporary error"
            return True, '{"invoices": []}', None

        client = ClaudeClient(CLAUDE_CONFIG, transport=flaky_transport)
        response = client.generate("test")

        self.assertTrue(response.success)
        self.assertEqual(attempts["count"], 2)

    def test_exhausts_retries_and_fails(self):
        def always_fail(prompt, config):
            return False, "", "always fails"

        client = ClaudeClient(CLAUDE_CONFIG, transport=always_fail)
        response = client.generate("test")

        self.assertFalse(response.success)
        self.assertEqual(response.attempt_count, 2)  # 1 initial + 1 retry

    def test_invalid_json_still_returns_success_with_none_parsed(self):
        def bad_json_transport(prompt, config):
            return True, "this is not json at all", None

        client = ClaudeClient(CLAUDE_CONFIG, transport=bad_json_transport)
        response = client.generate("test")

        self.assertTrue(response.success)
        self.assertIsNone(response.parsed_json)
        self.assertEqual(response.text, "this is not json at all")

    def test_generate_with_file_parses_json(self):
        """Primary path — send the PDF directly, same retry/parse wrapper as generate()."""
        import tempfile

        def fake_transport(prompt, config):
            return True, '{"invoices": [{"invoice_number": "INV001"}]}', None

        client = ClaudeClient(CLAUDE_CONFIG, transport=fake_transport)

        # generate_with_file() reads and base64-encodes the file from disk
        # before dispatching to the transport (matching the original Gemini
        # client's behavior) — the transport injection only bypasses the
        # network call, not the file read, so a real (even if dummy) file
        # is needed here.
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(b"%PDF-1.4 dummy content")
            f.flush()
            response = client.generate_with_file(f.name, "extract this")

        self.assertTrue(response.success)
        self.assertEqual(response.parsed_json["invoices"][0]["invoice_number"], "INV001")


class TestPdfplumberFallback(unittest.TestCase):

    def test_failed_schema_returned_for_nonexistent_file(self):
        from src.ai.pdfplumber_fallback import extract_with_pdfplumber
        result = extract_with_pdfplumber("nonexistent_file.pdf")

        self.assertIn("document_metadata", result)
        self.assertEqual(result["document_metadata"]["document_type"], "UNKNOWN")
        self.assertEqual(result["document_metadata"]["document_type_confidence"], 0.0)
        self.assertEqual(result["invoices"], [])

    def test_amount_parser(self):
        from src.ai.pdfplumber_fallback import _parse_amount
        self.assertEqual(_parse_amount("$1,234.56"), 1234.56)
        self.assertEqual(_parse_amount("48.75"), 48.75)
        self.assertIsNone(_parse_amount(None))
        self.assertIsNone(_parse_amount(""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
