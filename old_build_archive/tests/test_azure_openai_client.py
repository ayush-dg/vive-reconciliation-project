"""
tests/test_azure_openai_client.py

Tests for AzureOpenAIClient using injected fake transports.
No real API calls made — tests run fully offline.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["AZURE_OPENAI_TEST_API_KEY"] = "test-azure-key"
os.environ["AZURE_OPENAI_TEST_ENDPOINT"] = "https://test-resource.openai.azure.com/"
os.environ["AZURE_OPENAI_TEST_DEPLOYMENT"] = "gpt-5-mini"

from src.ai.azure_openai_client import AzureOpenAIClient

AZURE_CONFIG = {
    "provider": "azure_openai",
    "deployment_env_var": "AZURE_OPENAI_TEST_DEPLOYMENT",
    "endpoint_env_var": "AZURE_OPENAI_TEST_ENDPOINT",
    "api_key_env_var": "AZURE_OPENAI_TEST_API_KEY",
    "api_version": "2025-04-01-preview",
    "max_output_tokens": 8192,
    "timeout_seconds": 30,
    "retry_policy": {"max_retries": 1, "backoff_seconds": 0, "backoff_multiplier": 1},
}


class TestAzureOpenAIClient(unittest.TestCase):

    def test_successful_response_parses_json(self):
        def fake_transport(prompt, config):
            return True, '{"invoices": [], "document_metadata": {"document_type": "VENDOR_STATEMENT"}}', None

        client = AzureOpenAIClient(AZURE_CONFIG, transport=fake_transport)
        response = client.generate("extract this")

        self.assertTrue(response.success)
        self.assertIsNotNone(response.parsed_json)
        self.assertEqual(response.provider, "azure_openai")
        self.assertEqual(response.model, "gpt-5-mini")

    def test_missing_api_key_fails_cleanly(self):
        config = dict(AZURE_CONFIG, api_key_env_var="DEFINITELY_NOT_SET_XYZ")
        client = AzureOpenAIClient(config, transport=None)
        response = client.generate("test")

        self.assertFalse(response.success)
        self.assertIn("DEFINITELY_NOT_SET_XYZ", response.error)

    def test_missing_deployment_fails_cleanly(self):
        config = dict(AZURE_CONFIG, deployment_env_var="DEFINITELY_NOT_SET_DEPLOYMENT")
        client = AzureOpenAIClient(config, transport=None)
        response = client.generate("test")

        self.assertFalse(response.success)
        self.assertIn("DEFINITELY_NOT_SET_DEPLOYMENT", response.error)

    def test_retries_on_failure_then_succeeds(self):
        attempts = {"count": 0}

        def flaky_transport(prompt, config):
            attempts["count"] += 1
            if attempts["count"] < 2:
                return False, "", "temporary error"
            return True, '{"invoices": []}', None

        client = AzureOpenAIClient(AZURE_CONFIG, transport=flaky_transport)
        response = client.generate("test")

        self.assertTrue(response.success)
        self.assertEqual(attempts["count"], 2)

    def test_exhausts_retries_and_fails(self):
        def always_fail(prompt, config):
            return False, "", "always fails"

        client = AzureOpenAIClient(AZURE_CONFIG, transport=always_fail)
        response = client.generate("test")

        self.assertFalse(response.success)
        self.assertEqual(response.attempt_count, 2)  # 1 initial + 1 retry

    def test_invalid_json_still_returns_success_with_none_parsed(self):
        def bad_json_transport(prompt, config):
            return True, "this is not json at all", None

        client = AzureOpenAIClient(AZURE_CONFIG, transport=bad_json_transport)
        response = client.generate("test")

        self.assertTrue(response.success)
        self.assertIsNone(response.parsed_json)
        self.assertEqual(response.text, "this is not json at all")

    def test_generate_with_file_parses_json(self):
        """Primary path — send the PDF directly, same retry/parse wrapper as generate()."""
        import tempfile

        def fake_transport(prompt, config):
            return True, '{"invoices": [{"invoice_number": "INV001"}]}', None

        client = AzureOpenAIClient(AZURE_CONFIG, transport=fake_transport)

        # NamedTemporaryFile(delete=False) + explicit close before reopening —
        # a still-open NamedTemporaryFile handle can't be reopened on Windows.
        fd, path = tempfile.mkstemp(suffix=".pdf")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(b"%PDF-1.4 dummy content")
            response = client.generate_with_file(path, "extract this")
        finally:
            os.remove(path)

        self.assertTrue(response.success)
        self.assertEqual(response.parsed_json["invoices"][0]["invoice_number"], "INV001")

    def test_salvages_truncated_json(self):
        truncated = (
            '{"document_metadata": {"document_type": "VENDOR_STATEMENT"}, '
            '"invoices": [{"invoice_number": "INV001", "amount": 100.0}, '
            '{"invoice_number": "INV002", "amount": 50.0}, {"invoice_number": "IN'
        )

        def fake_transport(prompt, config):
            return True, truncated, None

        client = AzureOpenAIClient(AZURE_CONFIG, transport=fake_transport)
        response = client.generate("test")

        self.assertTrue(response.success)
        self.assertIsNotNone(response.parsed_json)
        self.assertEqual(len(response.parsed_json["invoices"]), 2)
        self.assertTrue(response.parsed_json["_salvaged"])

    def test_extract_text_or_error_handles_incomplete_status(self):
        class FakeIncompleteDetails:
            reason = "max_output_tokens"

        class FakeResponse:
            status = "incomplete"
            incomplete_details = FakeIncompleteDetails()
            output_text = ""

        client = AzureOpenAIClient(AZURE_CONFIG)
        success, text, error = client._extract_text_or_error(FakeResponse())

        self.assertFalse(success)
        self.assertIn("max_output_tokens", error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
