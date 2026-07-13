"""
tests/test_ai_clients.py

Tests for GeminiClient and GroqClient using injected fake transports.
No real API calls made — tests run fully offline.
"""

import os
import sys
import unittest

# Make src importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["GEMINI_API_KEY"] = "test-gemini-key"
os.environ["GROQ_API_KEY"] = "test-groq-key"

from src.ai.gemini_client import GeminiClient
from src.ai.groq_client import GroqClient

GEMINI_CONFIG = {
    "provider": "gemini",
    "model": "gemini-2.5-flash",
    "api_key_env_var": "GEMINI_API_KEY",
    "temperature": 0.1,
    "max_output_tokens": 8192,
    "timeout_seconds": 30,
    "retry_policy": {"max_retries": 1, "backoff_seconds": 0, "backoff_multiplier": 1},
}

GROQ_CONFIG = {
    "provider": "groq",
    "model": "llama-3.3-70b-versatile",
    "api_key_env_var": "GROQ_API_KEY",
    "temperature": 0.1,
    "max_output_tokens": 8192,
    "timeout_seconds": 30,
    "retry_policy": {"max_retries": 1, "backoff_seconds": 0, "backoff_multiplier": 1},
}


class TestGeminiClient(unittest.TestCase):

    def test_successful_response_parses_json(self):
        def fake_transport(prompt, config):
            return True, '{"invoices": [], "document_metadata": {"document_type": "VENDOR_STATEMENT"}}', None

        client = GeminiClient(GEMINI_CONFIG, transport=fake_transport)
        response = client.generate("extract this")

        self.assertTrue(response.success)
        self.assertIsNotNone(response.parsed_json)
        self.assertEqual(response.provider, "gemini")

    def test_missing_api_key_fails_cleanly(self):
        config = dict(GEMINI_CONFIG, api_key_env_var="DEFINITELY_NOT_SET_XYZ")
        client = GeminiClient(config, transport=None)
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

        client = GeminiClient(GEMINI_CONFIG, transport=flaky_transport)
        response = client.generate("test")

        self.assertTrue(response.success)
        self.assertEqual(attempts["count"], 2)

    def test_exhausts_retries_and_fails(self):
        def always_fail(prompt, config):
            return False, "", "always fails"

        client = GeminiClient(GEMINI_CONFIG, transport=always_fail)
        response = client.generate("test")

        self.assertFalse(response.success)
        self.assertEqual(response.attempt_count, 2)  # 1 initial + 1 retry

    def test_invalid_json_still_returns_success_with_none_parsed(self):
        def bad_json_transport(prompt, config):
            return True, "this is not json at all", None

        client = GeminiClient(GEMINI_CONFIG, transport=bad_json_transport)
        response = client.generate("test")

        self.assertTrue(response.success)
        self.assertIsNone(response.parsed_json)
        self.assertEqual(response.text, "this is not json at all")


class TestGroqClient(unittest.TestCase):

    def test_successful_response(self):
        def fake_transport(prompt, config):
            return True, '{"invoices": [{"invoice_number": "INV001"}]}', None

        client = GroqClient(GROQ_CONFIG, transport=fake_transport)
        response = client.generate("extract invoices")

        self.assertTrue(response.success)
        self.assertEqual(response.provider, "groq")
        self.assertEqual(response.parsed_json["invoices"][0]["invoice_number"], "INV001")

    def test_missing_api_key_fails_cleanly(self):
        config = dict(GROQ_CONFIG, api_key_env_var="DEFINITELY_NOT_SET_ABC")
        client = GroqClient(config, transport=None)
        response = client.generate("test")

        self.assertFalse(response.success)

    def test_rate_limit_retries(self):
        attempts = {"count": 0}

        def rate_limited(prompt, config):
            attempts["count"] += 1
            if attempts["count"] == 1:
                return False, "", "429 rate limited"
            return True, '{"invoices": []}', None

        client = GroqClient(GROQ_CONFIG, transport=rate_limited)
        response = client.generate("test")

        self.assertTrue(response.success)
        self.assertEqual(attempts["count"], 2)


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
