"""
tests/test_explanation_service.py

Tests for ExplanationService using fake AI transport.
No real API calls.
"""

import os
import sys
import json
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["GEMINI_API_KEY"] = "test-key"
os.environ["GROQ_API_KEY"] = "test-key"


SAMPLE_EXPLANATION = {
    "probable_cause": "The invoice was not posted in the ERP system by the statement cutoff date.",
    "suggested_resolution": "Contact the accounts payable team to confirm posting status and request manual entry if needed.",
    "confidence_score": 0.88,
    "business_impact": "LOW"
}

SAMPLE_EXCEPTION = {
    "exception_id": "test-exc-001",
    "vendor_id": "ASTECH",
    "invoice_number": "SIN12200241",
    "exception_reason": "Invoice Missing",
    "statement_amount": 48.75,
    "erp_amount": None,
    "ro_number": "6228719",
    "shop": "Vive Collision - Collex Auto Body",
    "statement_period": "2026-05",
    "exception_status": "OPEN",
}


class TestExplanationService(unittest.TestCase):

    def test_prompt_is_built_from_exception_fields(self):
        """The prompt should include the exception's key fields."""
        from src.ai.explanation_service import EXPLANATION_PROMPT_TEMPLATE
        prompt = EXPLANATION_PROMPT_TEMPLATE.format(
            vendor_id=SAMPLE_EXCEPTION["vendor_id"],
            invoice_number=SAMPLE_EXCEPTION["invoice_number"],
            exception_reason=SAMPLE_EXCEPTION["exception_reason"],
            statement_amount=SAMPLE_EXCEPTION["statement_amount"],
            erp_amount_str="not in ERP",
            ro_number=SAMPLE_EXCEPTION["ro_number"],
            shop=SAMPLE_EXCEPTION["shop"],
            statement_period=SAMPLE_EXCEPTION["statement_period"],
        )
        self.assertIn("SIN12200241", prompt)
        self.assertIn("Invoice Missing", prompt)
        self.assertIn("ASTECH", prompt)
        self.assertIn("48.75", prompt)

    def test_explanation_response_parsed_correctly(self):
        """A valid AI response should produce the right explanation fields."""
        import src.ai.client_factory as factory
        original_get = factory.get_ai_client
        original_chain = factory.get_provider_chain

        def fake_get_client(provider_name=None):
            from src.ai.gemini_client import GeminiClient
            config = {
                "provider": "gemini", "model": "gemini-2.5-flash",
                "api_key_env_var": "GEMINI_API_KEY", "temperature": 0.3,
                "max_output_tokens": 500, "timeout_seconds": 10,
                "retry_policy": {"max_retries": 0, "backoff_seconds": 0, "backoff_multiplier": 1}
            }
            def transport(prompt, cfg):
                return True, json.dumps(SAMPLE_EXPLANATION), None
            return GeminiClient(config, transport=transport)

        # Pin the provider chain explicitly — the real config/ai/active_provider.json
        # is allowed to change (e.g. groq-first while a quota is exhausted), and this
        # test asserts gemini specifically, so that ordering must not leak in from disk.
        factory.get_ai_client = fake_get_client
        factory.get_provider_chain = lambda: ["gemini", "groq", "pdfplumber"]

        written = {}

        from src.ai.explanation_service import ExplanationService
        svc = ExplanationService(max_per_run=5)

        # Override _write_explanation to capture instead of DB write
        def fake_write(exception_id, explanation, suggested_resolution, confidence_score, provider):
            written["explanation"] = explanation
            written["suggested_resolution"] = suggested_resolution
            written["confidence_score"] = confidence_score
            written["provider"] = provider

        svc._write_explanation = fake_write

        try:
            result = svc._explain_one(SAMPLE_EXCEPTION, "STMT-TEST")
            self.assertTrue(result)
            self.assertIn("not posted", written.get("explanation", ""))
            self.assertAlmostEqual(written.get("confidence_score"), 0.88)
            self.assertEqual(written.get("provider"), "gemini")
        finally:
            factory.get_ai_client = original_get
            factory.get_provider_chain = original_chain

    def test_explanation_falls_back_to_groq_when_gemini_fails(self):
        """When Gemini fails, Groq should be tried for explanations."""
        import src.ai.client_factory as factory
        original_get = factory.get_ai_client
        original_chain = factory.get_provider_chain
        groq_called = {"count": 0}

        def fake_get_client(provider_name=None):
            if provider_name == "gemini":
                from src.ai.gemini_client import GeminiClient
                config = {
                    "provider": "gemini", "model": "gemini-2.5-flash",
                    "api_key_env_var": "GEMINI_API_KEY", "temperature": 0.3,
                    "max_output_tokens": 100, "timeout_seconds": 5,
                    "retry_policy": {"max_retries": 0, "backoff_seconds": 0, "backoff_multiplier": 1}
                }
                return GeminiClient(config, transport=lambda p, c: (False, "", "quota exceeded"))
            elif provider_name == "groq":
                from src.ai.groq_client import GroqClient
                config = {
                    "provider": "groq", "model": "llama-3.3-70b-versatile",
                    "api_key_env_var": "GROQ_API_KEY", "temperature": 0.3,
                    "max_output_tokens": 100, "timeout_seconds": 5,
                    "retry_policy": {"max_retries": 0, "backoff_seconds": 0, "backoff_multiplier": 1}
                }
                def transport(p, c):
                    groq_called["count"] += 1
                    return True, json.dumps(SAMPLE_EXPLANATION), None
                return GroqClient(config, transport=transport)

        factory.get_ai_client = fake_get_client
        factory.get_provider_chain = lambda: ["gemini", "groq", "pdfplumber"]

        from src.ai.explanation_service import ExplanationService
        svc = ExplanationService(max_per_run=5)
        svc._write_explanation = lambda *a, **k: None  # skip DB write

        try:
            result = svc._explain_one(SAMPLE_EXCEPTION, "STMT-TEST")
            self.assertTrue(result)
            self.assertEqual(groq_called["count"], 1)
        finally:
            factory.get_ai_client = original_get
            factory.get_provider_chain = original_chain

    def test_max_per_run_limits_explanations(self):
        """ExplanationService should respect max_per_run setting."""
        from src.ai.explanation_service import ExplanationService
        svc = ExplanationService(max_per_run=3)
        self.assertEqual(svc.max_per_run, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
