"""
tests/test_document_understanding_engine.py

Tests for the Document Understanding Engine using injected fake providers.
No network calls, no real PDFs.
"""

import os
import sys
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
            "confidence_threshold": 0.60
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
            "confidence_threshold": 0.60
        }
        good_invoice = {
            "invoice_number": "INV-001",
            "outstanding_amount": 500.0,
            "line_confidence": 0.95
        }
        is_valid, reason = intake.validate_invoice(good_invoice, rules)
        self.assertTrue(is_valid)
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
