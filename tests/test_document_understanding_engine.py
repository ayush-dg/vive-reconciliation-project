"""
tests/test_document_understanding_engine.py

Tests for the Document Understanding Engine using injected fake providers.
No network calls, no real PDFs.
"""

import os
import sqlite3
import sys
import tempfile
import unittest
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["ANTHROPIC_API_KEY"] = "test-key"

# The active provider (from provider_chain in active_provider.json — currently
# Azure OpenAI gpt-5-mini) is the only AI path, tried on every PDF regardless
# of this text's length. pdf_text itself is no longer consulted by the engine
# (both the primary and fallback paths read the PDF file directly); it's
# only accepted for call-site compatibility with notebooks/01_document_intake.py.
SAMPLE_PDF_TEXT = (
    "sample pdf text extracted by pdfplumber from a normal text-based statement PDF — "
    "unused by the engine itself, kept only for call-site compatibility"
)

SAMPLE_SCHEMA_RESULT = {
    "document_metadata": {
        "document_type": "VENDOR_STATEMENT",
        "source_file": "test.pdf",
        "page_count": 2,
        "document_type_confidence": 0.95
    },
    "vendor_metadata": {
        "vendor_name": "Test Vendor Inc",
        "vendor_address": "123 Main St",
        "shop_or_entity": ["Vive Collision - Test Shop"],
        "vendor_confidence": 0.92
    },
    "statement_metadata": {
        "statement_date": "2026-05-31",
        "statement_period_start": "2026-05-01",
        "statement_period_end": "2026-05-31",
        "currency": "USD",
        "statement_total_as_printed": 1250.50,
        "statement_confidence": 0.90
    },
    "invoices": [
        {
            "invoice_number": "INV-001",
            "invoice_date": "2026-05-01",
            "due_date": "2026-05-31",
            "amount": 500.00,
            "outstanding_amount": 500.00,
            "ro_number": "RO-12345",
            "po_number": None,
            "work_order_number": None,
            "description": "Auto repair services",
            "credit": None,
            "shop": "Vive Collision - Test Shop",
            "page_number": 1,
            "row_number": 1,
            "line_confidence": 0.95
        },
        {
            "invoice_number": "INV-002",
            "invoice_date": "2026-05-15",
            "due_date": "2026-06-14",
            "amount": 750.50,
            "outstanding_amount": 750.50,
            "ro_number": "RO-12346",
            "po_number": None,
            "work_order_number": None,
            "description": "Parts and labor",
            "credit": None,
            "shop": "Vive Collision - Test Shop",
            "page_number": 1,
            "row_number": 2,
            "line_confidence": 0.93
        }
    ],
    "extraction_confidence": {
        "overall": 0.93,
        "table_detection_confidence": 0.97,
        "column_mapping_confidence": 0.90
    },
    "warnings": []
}


class FakeAIClient:
    """Fake client with both text and vision methods stubbed — stands in for
    whichever provider is active (Azure OpenAI gpt-5-mini today, Claude
    previously); the engine only depends on the AIClient interface."""
    def __init__(self, generate_result=None, vision_result=None):
        self._generate = generate_result
        self._vision = vision_result
        self.model = "gpt-5-mini"
        self.config = {"model": "gpt-5-mini"}

    def generate(self, prompt, **kwargs):
        return self._generate

    def generate_with_file(self, pdf_path, prompt):
        return self._vision


def make_response(success=True, parsed=None, provider="azure_openai", error=None):
    from src.ai.base_client import AIResponse
    return AIResponse(
        success=success,
        text=json.dumps(parsed) if parsed else "",
        parsed_json=parsed,
        model="gpt-5-mini",
        provider=provider,
        latency_ms=100.0,
        attempt_count=1,
        error=error,
    )


class TestDocumentUnderstandingEngine(unittest.TestCase):

    def test_engine_uses_active_provider_first(self):
        """The active provider (get_ai_client() with no args, resolved from
        provider_chain) is the primary (and only AI) path for any PDF."""
        import src.ai.client_factory as factory
        original_get = factory.get_ai_client

        vision_called = {"count": 0}

        def fake_get_client(provider_name=None):
            if provider_name is None:
                client = FakeAIClient(
                    vision_result=make_response(parsed=SAMPLE_SCHEMA_RESULT, provider="azure_openai")
                )
                original_vision = client.generate_with_file
                def counted_vision(pdf_path, prompt):
                    vision_called["count"] += 1
                    return original_vision(pdf_path, prompt)
                client.generate_with_file = counted_vision
                return client
            raise ValueError(f"Unexpected: {provider_name}")

        factory.get_ai_client = fake_get_client
        try:
            from src.ai.document_understanding_engine import DocumentUnderstandingEngine
            engine = DocumentUnderstandingEngine()
            result = engine.understand(SAMPLE_PDF_TEXT, "test.pdf")

            self.assertEqual(vision_called["count"], 1)
            self.assertEqual(result["_provider_used"], "azure_openai")
            self.assertEqual(len(result["invoices"]), 2)
        finally:
            factory.get_ai_client = original_get

    def test_engine_falls_back_to_pdfplumber_when_vision_fails(self):
        """When the active provider fails, fallback is deterministic
        pdfplumber — there's no second AI provider in the chain to try."""
        import src.ai.client_factory as factory
        original_get = factory.get_ai_client

        def fake_get_client(provider_name=None):
            if provider_name is None:
                return FakeAIClient(
                    vision_result=make_response(success=False, error="Vision quota exceeded", provider="azure_openai")
                )
            raise ValueError(f"Unexpected: {provider_name}")

        factory.get_ai_client = fake_get_client
        try:
            from src.ai.document_understanding_engine import DocumentUnderstandingEngine
            engine = DocumentUnderstandingEngine()
            # Nonexistent file — extract_with_pdfplumber() catches this and
            # returns its own failed-schema result; this test only checks
            # that routing lands on pdfplumber, not extraction quality.
            result = engine.understand(SAMPLE_PDF_TEXT, "nonexistent.pdf")

            self.assertEqual(result["_provider_used"], "pdfplumber")
            self.assertEqual(result["document_metadata"]["document_type"], "UNKNOWN")
        finally:
            factory.get_ai_client = original_get

    def test_extracted_invoices_have_required_fields(self):
        """Verify the sample result has all required invoice fields."""
        invoices = SAMPLE_SCHEMA_RESULT["invoices"]
        required = ["invoice_number", "outstanding_amount", "page_number", "row_number", "line_confidence"]
        for inv in invoices:
            for field in required:
                self.assertIn(field, inv, f"Missing field: {field}")

    def test_validate_invoice_rejects_missing_invoice_number(self):
        """Validation should reject invoices missing mandatory fields."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        # Import the validation function from the intake script
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "intake",
            os.path.join(os.path.dirname(__file__), "..", "notebooks", "01_document_intake.py")
        )
        intake = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(intake)

        rules = {
            "required_fields": ["invoice_number", "outstanding_amount"],
            "numeric_fields": ["outstanding_amount"],
            "confidence_threshold": 0.90
        }
        bad_invoice = {"outstanding_amount": 100.0, "line_confidence": 0.9}
        is_valid, reason = intake.validate_invoice(bad_invoice, rules)
        self.assertFalse(is_valid)
        self.assertIn("MISSING_MANDATORY_FIELD", reason)

    def test_validate_invoice_accepts_good_record(self):
        """A complete invoice should pass validation."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "intake",
            os.path.join(os.path.dirname(__file__), "..", "notebooks", "01_document_intake.py")
        )
        intake = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(intake)

        rules = {
            "required_fields": ["invoice_number", "outstanding_amount"],
            "numeric_fields": ["outstanding_amount"],
            "confidence_threshold": 0.90
        }
        good_invoice = {
            "invoice_number": "INV-001",
            "outstanding_amount": 500.0,
            "line_confidence": 0.95
        }
        is_valid, reason = intake.validate_invoice(good_invoice, rules)
        self.assertTrue(is_valid)
        self.assertEqual(reason, "")

    @staticmethod
    def _load_intake_module():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "intake",
            os.path.join(os.path.dirname(__file__), "..", "notebooks", "01_document_intake.py")
        )
        intake = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(intake)
        return intake

    def test_get_skip_reason_no_invoice_number_and_no_ro_fallback(self):
        """A row with neither invoice_number nor ro_number is genuinely
        unusable — it can never be matched or reviewed against anything."""
        intake = self._load_intake_module()
        row = {"outstanding_amount": 100.0}
        self.assertEqual(intake.get_skip_reason(row), "no invoice identifier found")

    def test_get_skip_reason_missing_invoice_number_with_ro_fallback_is_not_skipped(self):
        """A ro_number is an acceptable fallback identifier — the row still
        goes through normal validation (and likely to the review queue),
        it just isn't dropped outright."""
        intake = self._load_intake_module()
        row = {"ro_number": "RO-123", "outstanding_amount": 100.0}
        self.assertEqual(intake.get_skip_reason(row), "")

    def test_get_skip_reason_no_amount_at_all_is_not_skipped(self):
        """Removed 2026-08-23 (INV-04 amendment, see docs/INVARIANTS.md) --
        a row with an invoice_number but no outstanding_amount, amount, or
        credit still has an identifier and now proceeds to Bronze/Silver
        like any other row. Whether it's a genuine exception is now the
        matching engine's decision, not extraction's."""
        intake = self._load_intake_module()
        row = {"invoice_number": "INV-001"}
        self.assertEqual(intake.get_skip_reason(row), "")

    def test_get_skip_reason_amount_present_is_not_skipped(self):
        intake = self._load_intake_module()
        row = {"invoice_number": "INV-001", "amount": 50.0}
        self.assertEqual(intake.get_skip_reason(row), "")

    def test_get_skip_reason_credit_alone_counts_as_an_amount(self):
        intake = self._load_intake_module()
        row = {"invoice_number": "INV-001", "credit": 25.0}
        self.assertEqual(intake.get_skip_reason(row), "")

    def test_get_skip_reason_blank_strings_count_as_missing(self):
        intake = self._load_intake_module()
        row = {"invoice_number": "  ", "ro_number": "", "outstanding_amount": None}
        self.assertEqual(intake.get_skip_reason(row), "no invoice identifier found")

    def test_get_skip_reason_complete_row_is_not_skipped(self):
        intake = self._load_intake_module()
        row = {"invoice_number": "INV-001", "outstanding_amount": 100.0}
        self.assertEqual(intake.get_skip_reason(row), "")


class TestCorruptedPDFHandling(unittest.TestCase):
    """A corrupted/non-PDF file must fail with a clean, specific error —
    not a raw pdfminer/pdfplumber traceback — and must never reach Bronze.
    See PIPELINE_VERIFICATION_REPORT.md Finding 5."""

    SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "migrations", "001_initial_schema.sql")

    def _make_garbage_pdf(self):
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.write(b"This is not a valid PDF file at all, just plain garbage bytes." * 10)
        f.close()
        self.addCleanup(os.remove, f.name)
        return f.name

    def test_extract_pdf_text_raises_corrupted_pdf_error_not_raw_exception(self):
        from src.ai.document_understanding_engine import CorruptedPDFError, extract_pdf_text

        garbage_path = self._make_garbage_pdf()
        with self.assertRaises(CorruptedPDFError) as ctx:
            extract_pdf_text(garbage_path)
        self.assertEqual(
            str(ctx.exception),
            "File is not a valid PDF or is corrupted — could not be opened",
        )

    def test_run_intake_fails_cleanly_and_writes_nothing_to_bronze(self):
        """Real intake path (run_intake(), same code the worker calls),
        against a real (in-memory) SQLite DB — not just the isolated
        extract_pdf_text() unit above."""
        from src.ai.document_understanding_engine import CorruptedPDFError

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with open(self.SCHEMA_PATH) as f:
            conn.executescript(f.read())

        def execute_sql(sql, params=None):
            cur = conn.execute(sql, params or [])
            conn.commit()
            return cur

        def execute_query(sql, params=None):
            cur = conn.execute(sql, params or [])
            return [dict(row) for row in cur.fetchall()]

        intake = self._load_intake_module_fresh()
        intake.execute_sql = execute_sql
        intake.execute_query = execute_query

        garbage_path = self._make_garbage_pdf()
        with self.assertRaises(CorruptedPDFError):
            intake.run_intake(pdf_path=garbage_path)

        bronze_rows = execute_query("SELECT COUNT(*) AS c FROM bronze_vendor_statement_raw")
        self.assertEqual(bronze_rows[0]["c"], 0)
        cache_rows = execute_query("SELECT COUNT(*) AS c FROM extraction_cache")
        self.assertEqual(cache_rows[0]["c"], 0)

    @staticmethod
    def _load_intake_module_fresh():
        # Load under a distinct module name from _load_intake_module()'s
        # "intake" so patching execute_sql/execute_query here can't leak
        # into (or be affected by) any other test's separately-loaded copy.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "intake_corrupted_pdf_test",
            os.path.join(os.path.dirname(__file__), "..", "notebooks", "01_document_intake.py")
        )
        intake = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(intake)
        return intake


if __name__ == "__main__":
    unittest.main(verbosity=2)
