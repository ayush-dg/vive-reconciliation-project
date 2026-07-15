"""
tests/test_claude_sonnet_client.py

Tests for ClaudeSonnetClient using injected fake transports (generate_with_file)
plus direct unit tests of its column-agnostic mapping logic (same behavior as
GeminiClient's, including the amount-fallback currency-shape guard). No real
API calls made — tests run fully offline.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["CLAUDE_SONNET_TEST_API_KEY"] = "test-claude-key"
os.environ["CLAUDE_SONNET_TEST_DEPLOYMENT"] = "claude-sonnet-4-6"

from src.ai.claude_sonnet_client import ClaudeSonnetClient

CLAUDE_SONNET_CONFIG = {
    "provider": "claude_sonnet",
    "model": "claude-sonnet-4-6",
    "api_key_env_var": "CLAUDE_SONNET_TEST_API_KEY",
    "endpoint_env_var": "CLAUDE_SONNET_TEST_ENDPOINT_UNSET",
    "deployment_env_var": "CLAUDE_SONNET_TEST_DEPLOYMENT",
    "temperature": 0.1,
    "max_output_tokens": 64000,
    "timeout_seconds": 60,
    "retry_policy": {"max_retries": 0, "backoff_seconds": 0, "backoff_multiplier": 1},
}


class TestClaudeSonnetClientGenerateWithFile(unittest.TestCase):

    def test_successful_extraction_via_transport(self):
        fake_schema = {
            "document_metadata": {
                "document_type": "VENDOR_STATEMENT", "source_file": "x.pdf",
                "page_count": None, "document_type_confidence": 0.6,
            },
            "vendor_metadata": {
                "vendor_name": None, "vendor_address": None,
                "shop_or_entity": [], "vendor_confidence": 0.1,
            },
            "statement_metadata": {
                "statement_date": None, "statement_period_start": None,
                "statement_period_end": None, "currency": "USD",
                "statement_total_as_printed": 100.0, "statement_confidence": 0.3,
            },
            "invoices": [{"invoice_number": "INV001", "outstanding_amount": 100.0}],
            "extraction_confidence": {"overall": 0.75, "table_detection_confidence": 0.8, "column_mapping_confidence": 0.8},
            "warnings": [],
            "columns_found": ["Invoice #", "Amount Due"],
        }

        def fake_transport(pdf_path, config):
            return True, fake_schema, None

        client = ClaudeSonnetClient(CLAUDE_SONNET_CONFIG, transport=fake_transport)
        response = client.generate_with_file("fake.pdf", "extract this")

        self.assertTrue(response.success)
        self.assertEqual(response.provider, "claude_sonnet")
        self.assertEqual(response.parsed_json["invoices"][0]["invoice_number"], "INV001")

    def test_missing_api_key_fails_cleanly(self):
        config = dict(CLAUDE_SONNET_CONFIG, api_key_env_var="DEFINITELY_NOT_SET_XYZ")
        client = ClaudeSonnetClient(config, transport=None)
        response = client.generate_with_file("fake.pdf", "extract this")

        self.assertFalse(response.success)
        self.assertIn("DEFINITELY_NOT_SET_XYZ", response.error)

    def test_missing_model_fails_cleanly(self):
        config = dict(CLAUDE_SONNET_CONFIG, deployment_env_var="DEFINITELY_NOT_SET_DEPLOYMENT")
        config.pop("model", None)
        client = ClaudeSonnetClient(config, transport=None)
        response = client.generate_with_file("fake.pdf", "extract this")

        self.assertFalse(response.success)
        self.assertIn("DEFINITELY_NOT_SET_DEPLOYMENT", response.error)

    def test_transport_failure_returns_clean_failure_not_exception(self):
        def failing_transport(pdf_path, config):
            return False, None, "quota exceeded"

        client = ClaudeSonnetClient(CLAUDE_SONNET_CONFIG, transport=failing_transport)
        response = client.generate_with_file("fake.pdf", "extract this")

        self.assertFalse(response.success)
        self.assertEqual(response.error, "quota exceeded")

    def test_missing_pdf_file_fails_cleanly_not_exception(self):
        client = ClaudeSonnetClient(CLAUDE_SONNET_CONFIG, transport=None)
        response = client.generate_with_file("this/path/does/not/exist.pdf", "extract this")

        self.assertFalse(response.success)
        self.assertIsNotNone(response.error)

    def test_generate_uses_transport_and_parses_json(self):
        def fake_transport(prompt, config):
            return True, '{"foo": "bar"}', None

        client = ClaudeSonnetClient(CLAUDE_SONNET_CONFIG, transport=fake_transport)
        response = client.generate("hello")

        self.assertTrue(response.success)
        self.assertEqual(response.parsed_json, {"foo": "bar"})


class TestClaudeSonnetClientStreaming(unittest.TestCase):
    """Direct tests that the real call path uses client.messages.stream() +
    get_final_message() rather than a plain messages.create() call — the
    whole point of this client (see module docstring)."""

    def _fake_stream_manager(self, text):
        fake_message = mock.MagicMock()
        fake_message.content = [mock.MagicMock(text=text)]

        fake_stream = mock.MagicMock()
        fake_stream.get_final_message.return_value = fake_message

        fake_manager = mock.MagicMock()
        fake_manager.__enter__ = mock.Mock(return_value=fake_stream)
        fake_manager.__exit__ = mock.Mock(return_value=False)
        return fake_manager

    @staticmethod
    def _write_temp_pdf():
        # Write-then-close-then-reopen (not tempfile.NamedTemporaryFile's
        # context-manager form) — Windows refuses to reopen a file that's
        # still held open by another handle, which is exactly the pattern
        # tests/test_ai_clients.py hits its known pre-existing failure with.
        fd, path = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as f:
            f.write(b"%PDF-1.4 dummy content")
        return path

    def test_generate_with_file_uses_streaming_call(self):
        response_json = json.dumps({"columns_found": ["Invoice #"], "rows": [{"Invoice #": "A1"}]})
        fake_manager = self._fake_stream_manager(response_json)

        fake_client = mock.MagicMock()
        fake_client.messages.stream.return_value = fake_manager

        pdf_path = self._write_temp_pdf()
        try:
            with mock.patch("anthropic.Anthropic", return_value=fake_client):
                client = ClaudeSonnetClient(CLAUDE_SONNET_CONFIG, transport=None)
                response = client.generate_with_file(pdf_path, "extract this")
        finally:
            os.remove(pdf_path)

        self.assertTrue(response.success)
        fake_client.messages.stream.assert_called_once()
        fake_manager.__enter__.return_value.get_final_message.assert_called_once()
        self.assertEqual(response.parsed_json["invoices"][0]["invoice_number"], "A1")

    def test_streaming_error_returns_clean_failure_not_exception(self):
        fake_client = mock.MagicMock()
        fake_client.messages.stream.side_effect = Exception("529 overloaded_error")

        pdf_path = self._write_temp_pdf()
        try:
            with mock.patch("anthropic.Anthropic", return_value=fake_client):
                client = ClaudeSonnetClient(CLAUDE_SONNET_CONFIG, transport=None)
                response = client.generate_with_file(pdf_path, "extract this")
        finally:
            os.remove(pdf_path)

        self.assertFalse(response.success)
        self.assertIn("overloaded", response.error)

    def test_uses_azure_foundry_client_when_endpoint_set(self):
        config = dict(CLAUDE_SONNET_CONFIG, endpoint_env_var="CLAUDE_SONNET_TEST_ENDPOINT")
        os.environ["CLAUDE_SONNET_TEST_ENDPOINT"] = "https://example.services.ai.azure.com/anthropic"

        response_json = json.dumps({"columns_found": ["Invoice #"], "rows": [{"Invoice #": "A1"}]})
        fake_manager = self._fake_stream_manager(response_json)

        fake_client = mock.MagicMock()
        fake_client.messages.stream.return_value = fake_manager

        pdf_path = self._write_temp_pdf()
        try:
            with mock.patch("anthropic.AnthropicFoundry", return_value=fake_client) as foundry_ctor:
                client = ClaudeSonnetClient(config, transport=None)
                response = client.generate_with_file(pdf_path, "extract this")
        finally:
            os.remove(pdf_path)
            del os.environ["CLAUDE_SONNET_TEST_ENDPOINT"]

        self.assertTrue(response.success)
        foundry_ctor.assert_called_once()


class TestClaudeSonnetClientColumnMapping(unittest.TestCase):
    """Direct unit tests of the column-agnostic mapping logic (same as
    GeminiClient's)."""

    def setUp(self):
        self.client = ClaudeSonnetClient(CLAUDE_SONNET_CONFIG, transport=lambda *a: (False, None, "unused"))

    def test_single_invoice_column_simple_vendor(self):
        columns = ["Invoice #", "Invoice Date", "Amount Due"]
        rows = [{"Invoice #": "INV100", "Invoice Date": "05/01/2026", "Amount Due": "250.00"}]
        invoices, fallback_warnings = self.client._rows_to_invoices(rows, columns)

        inv = invoices[0]
        self.assertEqual(inv["invoice_number"], "INV100")
        self.assertEqual(inv["outstanding_amount"], 250.00)
        self.assertEqual(fallback_warnings, [])

    def test_dual_invoice_columns_prefers_column_without_account_code(self):
        columns = ["INVOICE NUMBER", "INVOICE NO.", "Amount Due"]
        rows = [
            {"INVOICE NUMBER": "60 35 8923821", "INVOICE NO.": "8923821", "Amount Due": "706.29"},
            {"INVOICE NUMBER": "60 35 8941124", "INVOICE NO.": "8941124", "Amount Due": "395.85"},
        ]
        invoices, _ = self.client._rows_to_invoices(rows, columns)

        self.assertEqual(invoices[0]["invoice_number"], "8923821")
        self.assertEqual(invoices[1]["invoice_number"], "8941124")

    def test_credit_column_mapped_separately_from_charges(self):
        columns = ["Invoice #", "Charges", "Payments"]
        rows = [{"Invoice #": "A1", "Charges": "100.00", "Payments": "50.00"}]
        invoices, _ = self.client._rows_to_invoices(rows, columns)

        self.assertEqual(invoices[0]["amount"], 100.00)
        self.assertEqual(invoices[0]["credit"], 50.00)

    def test_no_rows_returns_empty_list(self):
        self.assertEqual(self.client._rows_to_invoices([], ["Invoice #"]), ([], []))

    def test_non_dict_rows_are_skipped_not_crashed_on(self):
        columns = ["Invoice #", "Amount Due"]
        rows = [{"Invoice #": "A1", "Amount Due": "10.00"}, "not a dict", None]
        invoices, _ = self.client._rows_to_invoices(rows, columns)
        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0]["invoice_number"], "A1")


class TestClaudeSonnetClientTolerantFallbackMapping(unittest.TestCase):
    """Direct unit tests for the value-based fallback mapping, including the
    currency-shape guard that stops a bare invoice-number-shaped duplicate
    column from being mistaken for an amount (see module docstring — the
    exact bug class found validating GeminiClient against
    Fred_Beans_MidNJ_053126.pdf)."""

    def setUp(self):
        self.client = ClaudeSonnetClient(CLAUDE_SONNET_CONFIG, transport=lambda *a: (False, None, "unused"))

    def test_unrecognized_columns_fall_back_to_scanning_row_values(self):
        columns = ["Col A", "Col B", "Col C"]
        rows = [{"Col A": "12DEC25", "Col B": "8923821", "Col C": "706.29"}]
        invoices, fallback_warnings = self.client._rows_to_invoices(rows, columns)

        inv = invoices[0]
        self.assertEqual(inv["invoice_number"], "8923821")
        self.assertEqual(inv["outstanding_amount"], 706.29)
        self.assertEqual(len(fallback_warnings), 1)

    def test_fallback_never_reuses_the_invoice_number_value_as_amount(self):
        columns = ["Col A", "Col B"]
        rows = [{"Col A": "12DEC25", "Col B": "8923821"}]
        invoices, fallback_warnings = self.client._rows_to_invoices(rows, columns)

        inv = invoices[0]
        self.assertEqual(inv["invoice_number"], "8923821")
        self.assertIsNone(inv["outstanding_amount"])

    def test_fallback_amount_rejects_bare_invoice_number_shaped_duplicate_column(self):
        """Regression guard for the real $90M-statement-total bug found
        validating GeminiClient: a duplicate, unmapped column repeating the
        bare invoice number (no cents, no $ sign) must not be accepted as
        the fallback amount just because it parses as a float."""
        columns = ["Invoice #", "Some Unmapped Column"]
        rows = [{"Invoice #": "8923821,", "Some Unmapped Column": "8923821"}]
        invoices, fallback_warnings = self.client._rows_to_invoices(rows, columns)

        inv = invoices[0]
        self.assertEqual(inv["invoice_number"], "8923821,")
        self.assertIsNone(inv["outstanding_amount"])

    def test_row_with_recognized_columns_does_not_trigger_fallback(self):
        columns = ["Invoice #", "Amount Due"]
        rows = [{"Invoice #": "A1", "Amount Due": "10.00"}]
        invoices, fallback_warnings = self.client._rows_to_invoices(rows, columns)

        self.assertEqual(fallback_warnings, [])
        self.assertEqual(invoices[0]["invoice_number"], "A1")

    def test_partial_row_only_amount_missing(self):
        columns = ["Invoice #", "Amount Due", "Note"]
        rows = [{"Invoice #": "A1", "Amount Due": None, "Note": "42.50"}]
        invoices, fallback_warnings = self.client._rows_to_invoices(rows, columns)

        self.assertEqual(invoices[0]["invoice_number"], "A1")
        self.assertEqual(invoices[0]["outstanding_amount"], 42.50)
        self.assertEqual(len(fallback_warnings), 1)

    def test_looks_like_invoice_number_rejects_dates_and_currency(self):
        self.assertFalse(ClaudeSonnetClient._looks_like_invoice_number("05/01/2026"))
        self.assertFalse(ClaudeSonnetClient._looks_like_invoice_number("12DEC25"))
        self.assertFalse(ClaudeSonnetClient._looks_like_invoice_number("$48.75"))
        self.assertFalse(ClaudeSonnetClient._looks_like_invoice_number("1,234.56"))
        self.assertFalse(ClaudeSonnetClient._looks_like_invoice_number(None))
        self.assertFalse(ClaudeSonnetClient._looks_like_invoice_number(""))

    def test_looks_like_invoice_number_accepts_realistic_shapes(self):
        for value in ("8923821", "SIN12200241", "CM8923821", "366377-1"):
            self.assertTrue(ClaudeSonnetClient._looks_like_invoice_number(value), value)

    def test_aggregate_fallback_warning_added_to_schema(self):
        fake_schema_invoices = [{"invoice_number": "A1", "outstanding_amount": 1.0}]
        result = self.client._build_schema(
            "x.pdf", fake_schema_invoices, ["Col A"], salvaged=False,
            fallback_warnings=["Row 1: ...", "Row 2: ..."],
        )
        messages = [w["message"] for w in result["warnings"]]
        self.assertTrue(any("2 row(s)" in m for m in messages))


class TestClaudeSonnetClientToFloat(unittest.TestCase):

    def test_numeric_passthrough(self):
        self.assertEqual(ClaudeSonnetClient._to_float(42), 42.0)
        self.assertEqual(ClaudeSonnetClient._to_float(42.5), 42.5)

    def test_handles_currency_and_commas(self):
        self.assertEqual(ClaudeSonnetClient._to_float("$1,234.56"), 1234.56)

    def test_handles_parenthesized_negative(self):
        self.assertEqual(ClaudeSonnetClient._to_float("(100.00)"), -100.00)

    def test_handles_trailing_minus(self):
        self.assertEqual(ClaudeSonnetClient._to_float("100.00-"), -100.00)

    def test_none_and_empty_string(self):
        self.assertIsNone(ClaudeSonnetClient._to_float(None))
        self.assertIsNone(ClaudeSonnetClient._to_float(""))


class TestClaudeSonnetClientJsonSalvage(unittest.TestCase):

    def setUp(self):
        self.client = ClaudeSonnetClient(CLAUDE_SONNET_CONFIG, transport=lambda *a: (False, None, "unused"))

    def test_valid_json_parses_without_salvage(self):
        text = '{"columns_found": ["Invoice #"], "rows": [{"Invoice #": "A1"}]}'
        parsed = self.client._try_parse_json(text)
        self.assertEqual(parsed["rows"][0]["Invoice #"], "A1")

    def test_salvages_rows_from_truncated_json(self):
        text = ('{"columns_found": ["Invoice #", "Amount"], "rows": '
                '[{"Invoice #": "A1", "Amount": "10.00"}, {"Invoice #": "A2", "Amount": "20.0')
        parsed = self.client._try_parse_json(text)
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.get("_salvaged"))
        self.assertEqual(len(parsed["rows"]), 1)
        self.assertEqual(parsed["rows"][0]["Invoice #"], "A1")

    def test_garbage_text_returns_none(self):
        self.assertIsNone(self.client._try_parse_json("not json at all"))
        self.assertIsNone(self.client._try_parse_json(""))
        self.assertIsNone(self.client._try_parse_json(None))


if __name__ == "__main__":
    unittest.main()
