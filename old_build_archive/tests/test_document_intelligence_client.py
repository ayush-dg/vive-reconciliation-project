"""
tests/test_document_intelligence_client.py

Tests for DocumentIntelligenceClient using injected fake transports.
No real API calls made — tests run fully offline.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["AZURE_DOC_INTEL_TEST_ENDPOINT"] = "https://test-resource.cognitiveservices.azure.com/"
os.environ["AZURE_DOC_INTEL_TEST_KEY"] = "test-doc-intel-key"

from src.ai.document_intelligence_client import DocumentIntelligenceClient

DOC_INTEL_CONFIG = {
    "provider": "azure_document_intelligence",
    "endpoint_env_var": "AZURE_DOC_INTEL_TEST_ENDPOINT",
    "api_key_env_var": "AZURE_DOC_INTEL_TEST_KEY",
    "model_id": "prebuilt-layout",
    "retry_policy": {"max_retries": 1, "backoff_seconds": 0, "backoff_multiplier": 1},
}

HEADER_ROW = ["Invoice Date", "Invoice #", "Work Order #", "RO #", "Outstanding Amount", "Due Date"]


class TestDocumentIntelligenceClient(unittest.TestCase):

    def test_single_table_with_header_extracts_invoices(self):
        table = [
            HEADER_ROW,
            ["05/01/2026", "SIN12200241", "24099679", "6228719", "$ 48.75", "05/31/2026"],
            ["05/01/2026", "SIN12200135", "24099392", "6228734", "$ 101.21", "05/31/2026"],
        ]

        def fake_transport(pdf_path, config):
            return True, [table], None

        client = DocumentIntelligenceClient(DOC_INTEL_CONFIG, transport=fake_transport)
        response = client.generate_with_file("fake.pdf", "extract this")

        self.assertTrue(response.success)
        self.assertEqual(response.provider, "azure_document_intelligence")
        invoices = response.parsed_json["invoices"]
        self.assertEqual(len(invoices), 2)
        self.assertEqual(invoices[0]["invoice_number"], "SIN12200241")
        self.assertEqual(invoices[0]["work_order_number"], "24099679")
        self.assertEqual(invoices[0]["ro_number"], "6228719")
        self.assertEqual(invoices[0]["outstanding_amount"], 48.75)
        self.assertEqual(invoices[0]["due_date"], "05/31/2026")

    def test_continuation_table_without_header_reuses_col_map(self):
        """Mirrors the real ASTCollex0526.pdf structure: only the first
        table has a header row, later tables (pages 2+) are pure data."""
        table0 = [
            HEADER_ROW,
            ["05/01/2026", "SIN12200241", "24099679", "6228719", "$ 48.75", "05/31/2026"],
        ]
        table1 = [
            ["05/08/2026", "SIN12233141", "24192585", "6228761", "$ 48.75", "06/07/2026"],
            ["05/08/2026", "SIN12233168", "24192586", "6228738", "$ 48.75", "06/07/2026"],
        ]

        def fake_transport(pdf_path, config):
            return True, [table0, table1], None

        client = DocumentIntelligenceClient(DOC_INTEL_CONFIG, transport=fake_transport)
        response = client.generate_with_file("fake.pdf", "extract this")

        self.assertTrue(response.success)
        invoices = response.parsed_json["invoices"]
        self.assertEqual(len(invoices), 3)  # 1 from table0 + 2 from table1
        self.assertEqual(invoices[1]["invoice_number"], "SIN12233141")
        self.assertEqual(invoices[1]["page_number"], 2)

    def test_trailing_totals_row_is_not_mistaken_for_a_header(self):
        """Regression test — a continuation table's trailing footer row
        ('Total Outstanding Invoices: ... $13,860.79 USD') contains both
        'outstanding' and 'invoice', tripping _find_header_row's >=2
        keyword threshold if not rejected for appearing at the bottom of
        the table rather than the top."""
        table0 = [
            HEADER_ROW,
            ["05/01/2026", "SIN12200241", "24099679", "6228719", "$ 48.75", "05/31/2026"],
        ]
        table1_with_footer = [
            ["05/08/2026", "SIN12233141", "24192585", "6228761", "$ 48.75", "06/07/2026"],
            ["05/18/2026", "SIN12270945", "24305204", "6228819", "$ 48.75", "06/17/2026"],
            ["05/29/2026", "SIN12320977", "24458334", "6228869", "$ 101.21", "06/28/2026"],
            ["Total Outstanding Invoices:", "", "", "", "$ 13,860.79", "USD"],
        ]

        def fake_transport(pdf_path, config):
            return True, [table0, table1_with_footer], None

        client = DocumentIntelligenceClient(DOC_INTEL_CONFIG, transport=fake_transport)
        response = client.generate_with_file("fake.pdf", "extract this")

        self.assertTrue(response.success)
        invoices = response.parsed_json["invoices"]
        # All 3 real data rows from table1 must survive; the footer line
        # (index 3, past HEADER_MAX_DATA_START) must not be misread as a
        # header and silently swallow everything before it.
        invoice_numbers = [inv["invoice_number"] for inv in invoices]
        self.assertIn("SIN12233141", invoice_numbers)
        self.assertIn("SIN12270945", invoice_numbers)
        self.assertIn("SIN12320977", invoice_numbers)

    def test_mismatched_column_count_table_is_skipped_with_warning(self):
        table0 = [HEADER_ROW, ["05/01/2026", "SIN12200241", "24099679", "6228719", "$ 48.75", "05/31/2026"]]
        bad_table = [["only", "three", "cols"]]

        def fake_transport(pdf_path, config):
            return True, [table0, bad_table], None

        client = DocumentIntelligenceClient(DOC_INTEL_CONFIG, transport=fake_transport)
        response = client.generate_with_file("fake.pdf", "extract this")

        self.assertTrue(response.success)
        self.assertEqual(len(response.parsed_json["invoices"]), 1)
        self.assertTrue(any("column count" in w["message"] for w in response.parsed_json["warnings"]))

    def test_no_tables_returns_success_with_warning(self):
        def fake_transport(pdf_path, config):
            return True, [], None

        client = DocumentIntelligenceClient(DOC_INTEL_CONFIG, transport=fake_transport)
        response = client.generate_with_file("fake.pdf", "extract this")

        self.assertTrue(response.success)
        self.assertEqual(response.parsed_json["invoices"], [])
        self.assertTrue(len(response.parsed_json["warnings"]) >= 1)

    def test_missing_endpoint_fails_cleanly(self):
        config = dict(DOC_INTEL_CONFIG, endpoint_env_var="DEFINITELY_NOT_SET_XYZ")
        client = DocumentIntelligenceClient(config, transport=None)
        response = client.generate_with_file("fake.pdf", "extract this")

        self.assertFalse(response.success)
        self.assertIn("DEFINITELY_NOT_SET_XYZ", response.error)

    def test_retries_on_failure_then_succeeds(self):
        attempts = {"count": 0}
        table = [HEADER_ROW, ["05/01/2026", "SIN12200241", "24099679", "6228719", "$ 48.75", "05/31/2026"]]

        def flaky_transport(pdf_path, config):
            attempts["count"] += 1
            if attempts["count"] < 2:
                return False, None, "temporary error"
            return True, [table], None

        client = DocumentIntelligenceClient(DOC_INTEL_CONFIG, transport=flaky_transport)
        response = client.generate_with_file("fake.pdf", "extract this")

        self.assertTrue(response.success)
        self.assertEqual(attempts["count"], 2)

    def test_generate_returns_clean_failure(self):
        """generate() (text-only) isn't applicable to a document-extraction
        service — confirm it fails cleanly rather than being left unimplemented."""
        client = DocumentIntelligenceClient(DOC_INTEL_CONFIG)
        response = client.generate("some prompt")

        self.assertFalse(response.success)
        self.assertIn("generate_with_file", response.error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
