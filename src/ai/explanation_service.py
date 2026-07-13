"""
explanation_service.py

Generates AI-powered, business-friendly explanations for reconciliation exceptions.

IMPORTANT: This service never changes match_status, exception_reason, or any
financial figure. It only adds narrative context to already-classified exceptions.
The deterministic matching engine's decisions are final.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.ai import client_factory
from src.ai.audit_logger import log_ai_call
from src.lakehouse.connection import execute_sql, execute_query


EXPLANATION_PROMPT_VERSION = "v1"

EXPLANATION_PROMPT_TEMPLATE = """You are a financial reconciliation analyst helping an accounts payable team.

A vendor statement reconciliation has identified the following exception. Provide a brief, business-friendly explanation.

Exception Details:
- Vendor: {vendor_id}
- Invoice Number: {invoice_number}
- Exception Type: {exception_reason}
- Statement Amount: ${statement_amount}
- ERP Amount: {erp_amount_str}
- RO Number: {ro_number}
- Shop: {shop}
- Statement Period: {statement_period}

Return a JSON object with exactly these fields:
{{
  "probable_cause": "1-2 sentences explaining what likely caused this exception",
  "suggested_resolution": "1-2 sentences suggesting what the AP team should do next",
  "confidence_score": <float 0.0-1.0 indicating how confident you are in this explanation>,
  "business_impact": "LOW | MEDIUM | HIGH"
}}

Be concise and practical. Focus on actionable next steps.
Return only valid JSON. No explanation or markdown outside the JSON.
"""


class ExplanationService:
    """
    Generates AI explanations for reconciliation exceptions.
    Reads from and writes to gold_exceptions.
    """

    def __init__(self, max_per_run: int = 10):
        """
        max_per_run: Maximum exceptions to explain per run.
        Set lower during development to conserve API quota.
        """
        self.max_per_run = max_per_run
        self.provider_chain = client_factory.get_provider_chain()

    def explain_all_open_exceptions(self, statement_id: str) -> dict:
        """
        Explain all OPEN exceptions for a given statement_id that don't yet
        have an AI explanation. Writes results back to gold_exceptions.

        Returns a summary dict.
        """
        # Find open exceptions without AI explanations yet
        exceptions = execute_query(
            """
            SELECT * FROM gold_exceptions
            WHERE statement_id = ?
              AND exception_status = 'OPEN'
              AND ai_explanation IS NULL
            ORDER BY exception_reason, invoice_number
            """,
            [statement_id]
        )

        if not exceptions:
            return {"explained": 0, "skipped": 0, "failed": 0}

        to_explain = exceptions[:self.max_per_run]
        skipped = len(exceptions) - len(to_explain)

        if skipped > 0:
            print(f"  [Explain] {len(exceptions)} exceptions found; "
                  f"processing {len(to_explain)} (limit={self.max_per_run})")
        else:
            print(f"  [Explain] Processing {len(to_explain)} open exceptions")

        explained = 0
        failed = 0

        for exc in to_explain:
            result = self._explain_one(exc, statement_id)
            if result:
                explained += 1
            else:
                failed += 1

        return {"explained": explained, "skipped": skipped, "failed": failed}

    def _explain_one(self, exception_row: dict, statement_id: str) -> bool:
        """
        Generate an AI explanation for a single exception row.
        Updates gold_exceptions in place.
        Returns True on success, False on failure.
        """
        invoice_number = exception_row.get("invoice_number", "unknown")
        erp_amount = exception_row.get("erp_amount")
        erp_amount_str = f"${erp_amount}" if erp_amount else "not in ERP"

        prompt = EXPLANATION_PROMPT_TEMPLATE.format(
            vendor_id=exception_row.get("vendor_id", "unknown"),
            invoice_number=invoice_number,
            exception_reason=exception_row.get("exception_reason", "unknown"),
            statement_amount=exception_row.get("statement_amount", 0),
            erp_amount_str=erp_amount_str,
            ro_number=exception_row.get("ro_number") or "N/A",
            shop=exception_row.get("shop") or "unknown",
            statement_period=exception_row.get("statement_period") or "unknown",
        )

        # Try each provider in chain
        for provider_name in self.provider_chain:
            if provider_name == "pdfplumber":
                # pdfplumber can't generate text explanations
                continue

            try:
                client = client_factory.get_ai_client(provider_name)
            except Exception as e:
                print(f"  [Explain] Could not load {provider_name}: {e}")
                continue

            response = client.generate(prompt, temperature=0.3)

            # Log the call
            try:
                log_ai_call(
                    response,
                    interaction_type="EXCEPTION_EXPLANATION",
                    prompt_version=EXPLANATION_PROMPT_VERSION,
                    statement_id=statement_id,
                    vendor_id=exception_row.get("vendor_id"),
                )
            except Exception:
                pass

            if response.success and response.parsed_json:
                explanation_data = response.parsed_json
                self._write_explanation(
                    exception_id=exception_row["exception_id"],
                    explanation=explanation_data.get("probable_cause", ""),
                    suggested_resolution=explanation_data.get("suggested_resolution", ""),
                    confidence_score=explanation_data.get("confidence_score"),
                    provider=provider_name,
                )
                print(f"  [Explain] {invoice_number} ({exception_row.get('exception_reason')}) "
                      f"— explained via {provider_name}")
                return True
            else:
                print(f"  [Explain] {provider_name} failed for {invoice_number}: {response.error}")
                continue

        # All providers failed
        print(f"  [Explain] All providers failed for {invoice_number}")
        return False

    def _write_explanation(self, exception_id: str, explanation: str,
                           suggested_resolution: str, confidence_score: float,
                           provider: str):
        """Write the AI explanation back to gold_exceptions."""
        execute_sql(
            """
            UPDATE gold_exceptions
            SET ai_explanation = ?,
                ai_suggested_resolution = ?,
                ai_confidence_score = ?,
                ai_provider = ?
            WHERE exception_id = ?
            """,
            [explanation, suggested_resolution, confidence_score, provider, exception_id]
        )
