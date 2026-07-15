"""
tests/test_gemini_client.py

Tests for GeminiClient using injected fake transports (generate_with_file)
plus direct unit tests of its column-agnostic mapping logic — the core
novel behavior of this client (no per-vendor config, and disambiguating
multiple invoice-number-like columns by content rather than header order).
No real API calls made — tests run fully offline.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["GEMINI_TEST_API_KEY"] = "test-gemini-key"
os.environ["GEMINI_TEST_MODEL"] = "gemini-2.5-flash"

from src.ai.gemini_client import GeminiClient

GEMINI_CONFIG = {
    "provider": "gemini",
    "model": "gemini-2.5-flash",
    "api_key_env_var": "GEMINI_TEST_API_KEY",
    "model_env_var": "GEMINI_TEST_MODEL",
    "temperature": 0.1,
    "timeout_seconds": 60,
    "retry_policy": {"max_retries": 0, "backoff_seconds": 0, "backoff_multiplier": 1},
}


class TestGeminiClientGenerateWithFile(unittest.TestCase):

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

        client = GeminiClient(GEMINI_CONFIG, transport=fake_transport)
        response = client.generate_with_file("fake.pdf", "extract this")

        self.assertTrue(response.success)
        self.assertEqual(response.provider, "gemini")
        self.assertEqual(response.parsed_json["invoices"][0]["invoice_number"], "INV001")

    def test_missing_api_key_fails_cleanly(self):
        config = dict(GEMINI_CONFIG, api_key_env_var="DEFINITELY_NOT_SET_XYZ")
        client = GeminiClient(config, transport=None)
        response = client.generate_with_file("fake.pdf", "extract this")

        self.assertFalse(response.success)
        self.assertIn("DEFINITELY_NOT_SET_XYZ", response.error)

    def test_missing_model_fails_cleanly(self):
        # Must also drop the static "model" fallback — the client falls back
        # to config["model"] when the env var is unset (same pattern as
        # ClaudeClient), so this test needs both absent to hit the real
        # "no model configured at all" path.
        config = dict(GEMINI_CONFIG, model_env_var="DEFINITELY_NOT_SET_MODEL")
        config.pop("model", None)
        client = GeminiClient(config, transport=None)
        response = client.generate_with_file("fake.pdf", "extract this")

        self.assertFalse(response.success)
        self.assertIn("DEFINITELY_NOT_SET_MODEL", response.error)

    def test_transport_failure_returns_clean_failure_not_exception(self):
        def failing_transport(pdf_path, config):
            return False, None, "quota exceeded"

        client = GeminiClient(GEMINI_CONFIG, transport=failing_transport)
        response = client.generate_with_file("fake.pdf", "extract this")

        self.assertFalse(response.success)
        self.assertEqual(response.error, "quota exceeded")

    def test_generate_uses_transport_and_parses_json(self):
        def fake_transport(prompt, config):
            return True, '{"foo": "bar"}', None

        client = GeminiClient(GEMINI_CONFIG, transport=fake_transport)
        response = client.generate("hello")

        self.assertTrue(response.success)
        self.assertEqual(response.parsed_json, {"foo": "bar"})


class TestGeminiClientColumnMapping(unittest.TestCase):
    """Direct unit tests of the column-agnostic mapping logic."""

    def setUp(self):
        self.client = GeminiClient(GEMINI_CONFIG, transport=lambda *a: (False, None, "unused"))

    def test_single_invoice_column_simple_vendor(self):
        columns = ["Invoice Date", "Invoice #", "Work Order #", "RO #", "Outstanding Amount", "Due Date"]
        rows = [{
            "Invoice Date": "05/01/2026", "Invoice #": "SIN12200241", "Work Order #": "24099679",
            "RO #": "6228719", "Outstanding Amount": "$ 48.75", "Due Date": "05/31/2026",
        }]
        invoices = self.client._rows_to_invoices(rows, columns)

        self.assertEqual(len(invoices), 1)
        inv = invoices[0]
        self.assertEqual(inv["invoice_number"], "SIN12200241")
        self.assertEqual(inv["outstanding_amount"], 48.75)
        self.assertEqual(inv["ro_number"], "6228719")
        self.assertEqual(inv["work_order_number"], "24099679")
        self.assertEqual(inv["due_date"], "05/31/2026")
        self.assertEqual(inv["invoice_date"], "05/01/2026")

    def test_dual_invoice_columns_prefers_column_without_account_code(self):
        """The Fred Beans case — two invoice-number-like columns, one with
        an account-code prefix, one clean. Must pick the clean one
        regardless of which column appears first in the header list."""
        columns = ["DATE", "INVOICE NUMBER", "CHARGES", "CREDITS", "AMOUNT DUE", "INVOICE NO."]
        rows = [
            {"DATE": "12DEC25", "INVOICE NUMBER": "60 35 8923821", "CHARGES": "706.29",
             "CREDITS": None, "AMOUNT DUE": None, "INVOICE NO.": "8923821"},
            {"DATE": "16FEB26", "INVOICE NUMBER": "99 57 8923821", "CHARGES": None,
             "CREDITS": "706.29", "AMOUNT DUE": None, "INVOICE NO.": "8923821"},
        ]
        invoices = self.client._rows_to_invoices(rows, columns)

        self.assertEqual(len(invoices), 2)
        for inv in invoices:
            self.assertEqual(inv["invoice_number"], "8923821")
            self.assertNotIn(" ", inv["invoice_number"])

    def test_dual_invoice_columns_order_independent(self):
        """Same as above but with the clean column listed FIRST — the
        cleanliness check must be content-based, not "prefer the last
        matching column"."""
        columns = ["DATE", "INVOICE NO.", "INVOICE NUMBER", "CHARGES"]
        rows = [
            {"DATE": "12DEC25", "INVOICE NO.": "8923821", "INVOICE NUMBER": "60 35 8923821", "CHARGES": "706.29"},
        ]
        invoices = self.client._rows_to_invoices(rows, columns)
        self.assertEqual(invoices[0]["invoice_number"], "8923821")

    def test_credit_column_mapped_separately_from_charges(self):
        columns = ["date", "invoice_number", "charges", "credits", "amount_due"]

        charge_row = [{"date": "12DEC25", "invoice_number": "8923821", "charges": 706.29,
                       "credits": None, "amount_due": None}]
        invoices = self.client._rows_to_invoices(charge_row, columns)
        self.assertEqual(invoices[0]["amount"], 706.29)
        self.assertIsNone(invoices[0]["credit"])

        credit_row = [{"date": "20FEB26", "invoice_number": "CM8923821", "charges": None,
                       "credits": 238.77, "amount_due": None}]
        invoices2 = self.client._rows_to_invoices(credit_row, columns)
        self.assertEqual(invoices2[0]["credit"], 238.77)

    def test_underscore_keys_normalize_same_as_literal_headers(self):
        """Gemini sometimes returns normalized snake_case keys instead of
        literal PDF headers (observed on Fred Beans specifically) — the
        mapper must handle both without special-casing."""
        columns = ["invoice_number", "amount_due"]
        rows = [{"invoice_number": "9050372", "amount_due": "150.00"}]
        invoices = self.client._rows_to_invoices(rows, columns)
        self.assertEqual(invoices[0]["invoice_number"], "9050372")
        self.assertEqual(invoices[0]["outstanding_amount"], 150.00)

    def test_tekion_style_purchases_payments_balance(self):
        columns = ["#", "Invoice Date", "Invoice#", "Purchases", "Payments", "Balance"]
        rows = [{"#": "1", "Invoice Date": "12/19/25", "Invoice#": "44395",
                 "Purchases": "$105.96", "Payments": None, "Balance": "$105.96"}]
        invoices = self.client._rows_to_invoices(rows, columns)
        inv = invoices[0]
        self.assertEqual(inv["invoice_number"], "44395")
        self.assertEqual(inv["amount"], 105.96)
        self.assertEqual(inv["outstanding_amount"], 105.96)

    def test_no_rows_returns_empty_list(self):
        self.assertEqual(self.client._rows_to_invoices([], ["Invoice #"]), [])

    def test_non_dict_rows_are_skipped_not_crashed_on(self):
        columns = ["Invoice #", "Amount Due"]
        rows = [{"Invoice #": "A1", "Amount Due": "10.00"}, "not a dict", None]
        invoices = self.client._rows_to_invoices(rows, columns)
        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0]["invoice_number"], "A1")


class TestGeminiClientToFloat(unittest.TestCase):

    def setUp(self):
        self.client = GeminiClient(GEMINI_CONFIG, transport=lambda *a: (False, None, "unused"))

    def test_handles_currency_and_commas(self):
        self.assertEqual(self.client._to_float("$1,234.56"), 1234.56)

    def test_handles_parenthesized_negative(self):
        self.assertEqual(self.client._to_float("(123.45)"), -123.45)

    def test_handles_trailing_minus(self):
        self.assertEqual(self.client._to_float("41.11-"), -41.11)

    def test_none_and_empty_string(self):
        self.assertIsNone(self.client._to_float(None))
        self.assertIsNone(self.client._to_float(""))

    def test_numeric_passthrough(self):
        self.assertEqual(self.client._to_float(48.75), 48.75)


class TestGeminiClientJsonSalvage(unittest.TestCase):

    def setUp(self):
        self.client = GeminiClient(GEMINI_CONFIG, transport=lambda *a: (False, None, "unused"))

    def test_salvages_rows_from_truncated_json(self):
        truncated = (
            '{"columns_found": ["Invoice #", "Amount Due"], "rows": '
            '[{"Invoice #": "A1", "Amount Due": "10.00"}, '
            '{"Invoice #": "A2", "Amount Due": "20.00"}, '
            '{"Invoice #": "A3", "Amount Du'  # cut off mid-object
        )
        parsed = self.client._try_parse_json(truncated)
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.get("_salvaged"))
        self.assertEqual(len(parsed["rows"]), 2)
        self.assertEqual(parsed["columns_found"], ["Invoice #", "Amount Due"])

    def test_valid_json_parses_without_salvage(self):
        text = '{"columns_found": ["A"], "rows": [{"A": "1"}]}'
        parsed = self.client._try_parse_json(text)
        self.assertEqual(parsed["rows"], [{"A": "1"}])
        self.assertNotIn("_salvaged", parsed)

    def test_garbage_text_returns_none(self):
        self.assertIsNone(self.client._try_parse_json("not json at all"))
        self.assertIsNone(self.client._try_parse_json(""))
        self.assertIsNone(self.client._try_parse_json(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
