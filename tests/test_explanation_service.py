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

os.environ["ANTHROPIC_API_KEY"] = "test-key"


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

        def fake_get_client(provider_name=None):
            self.assertEqual(provider_name, "claude")  # hardcoded, not read from provider_chain
            from src.ai.claude_client import ClaudeClient
            config = {
                "provider": "claude", "model": "claude-haiku-4-5-20251001",
                "api_key_env_var": "ANTHROPIC_API_KEY", "temperature": 0.3,
                "max_output_tokens": 500, "timeout_seconds": 10,
                "retry_policy": {"max_retries": 0, "backoff_seconds": 0, "backoff_multiplier": 1}
            }
            def transport(prompt, cfg):
                return True, json.dumps(SAMPLE_EXPLANATION), None
            return ClaudeClient(config, transport=transport)

        factory.get_ai_client = fake_get_client

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
            self.assertEqual(written.get("provider"), "claude")
        finally:
            factory.get_ai_client = original_get

    def test_explanation_fails_cleanly_when_claude_fails(self):
        """When Claude fails, there's no second AI provider — explanation
        generation should fail cleanly (return False), not crash."""
        import src.ai.client_factory as factory
        original_get = factory.get_ai_client

        def fake_get_client(provider_name=None):
            from src.ai.claude_client import ClaudeClient
            config = {
                "provider": "claude", "model": "claude-haiku-4-5-20251001",
                "api_key_env_var": "ANTHROPIC_API_KEY", "temperature": 0.3,
                "max_output_tokens": 100, "timeout_seconds": 5,
                "retry_policy": {"max_retries": 0, "backoff_seconds": 0, "backoff_multiplier": 1}
            }
            return ClaudeClient(config, transport=lambda p, c: (False, "", "quota exceeded"))

        factory.get_ai_client = fake_get_client

        from src.ai.explanation_service import ExplanationService
        svc = ExplanationService(max_per_run=5)
        svc._write_explanation = lambda *a, **k: None  # skip DB write

        try:
            result = svc._explain_one(SAMPLE_EXCEPTION, "STMT-TEST")
            self.assertFalse(result)
        finally:
            factory.get_ai_client = original_get

    def test_explanation_fails_cleanly_when_provider_cannot_load(self):
        """If get_ai_client("claude") itself raises (e.g. missing API key),
        explanation generation should fail cleanly, not crash."""
        import src.ai.client_factory as factory
        original_get = factory.get_ai_client

        def raising_get_client(provider_name=None):
            raise ValueError("Missing API key")

        factory.get_ai_client = raising_get_client

        from src.ai.explanation_service import ExplanationService
        svc = ExplanationService(max_per_run=5)
        svc._write_explanation = lambda *a, **k: None

        try:
            result = svc._explain_one(SAMPLE_EXCEPTION, "STMT-TEST")
            self.assertFalse(result)
        finally:
            factory.get_ai_client = original_get

    def test_max_per_run_limits_explanations(self):
        """ExplanationService should respect max_per_run setting."""
        from src.ai.explanation_service import ExplanationService
        svc = ExplanationService(max_per_run=3)
        self.assertEqual(svc.max_per_run, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
