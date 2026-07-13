"""
gemini_client.py

Gemini 2.5 Flash implementation of AIClient.
The ONLY file that knows Gemini's SDK/wire format.
"""

import json
import os
import time
from typing import Callable, Optional

from .base_client import AIClient, AIResponse


class GeminiClient(AIClient):
    def __init__(self, config: dict, transport: Optional[Callable] = None):
        """
        config   : parsed config/ai/gemini.json
        transport: optional injectable callable for testing.
                   Signature: (prompt, config) -> (success, text, error)
                   If None, uses the real google-genai SDK.
        """
        self.config = config
        self._transport = transport

        api_key_var = config.get("api_key_env_var", "GEMINI_API_KEY")
        self.api_key = os.environ.get(api_key_var)

    def generate(self, prompt: str, *, temperature=None, max_output_tokens=None) -> AIResponse:
        model = self.config["model"]
        temperature = temperature if temperature is not None else self.config.get("temperature", 0.1)
        max_tokens = max_output_tokens or self.config.get("max_output_tokens", 8192)
        timeout = self.config.get("timeout_seconds", 60)
        retry_policy = self.config.get("retry_policy", {})
        max_retries = retry_policy.get("max_retries", 2)
        backoff = retry_policy.get("backoff_seconds", 2)
        multiplier = retry_policy.get("backoff_multiplier", 2)

        if not self.api_key:
            return AIResponse(
                success=False,
                provider="gemini",
                model=model,
                error=f"Missing API key — env var '{self.config.get('api_key_env_var')}' not set"
            )

        start = time.monotonic()
        last_error = None

        for attempt in range(1, max_retries + 2):
            try:
                if self._transport:
                    success, text, error = self._transport(prompt, self.config)
                else:
                    success, text, error = self._real_gemini_call(
                        prompt, model, temperature, max_tokens, timeout
                    )

                latency_ms = (time.monotonic() - start) * 1000

                if success:
                    parsed = self._try_parse_json(text)
                    return AIResponse(
                        success=True,
                        text=text,
                        parsed_json=parsed,
                        model=model,
                        provider="gemini",
                        latency_ms=latency_ms,
                        attempt_count=attempt,
                    )
                else:
                    last_error = error
                    if attempt <= max_retries:
                        time.sleep(backoff * (multiplier ** (attempt - 1)))

            except Exception as e:
                last_error = str(e)
                if attempt <= max_retries:
                    time.sleep(backoff * (multiplier ** (attempt - 1)))

        latency_ms = (time.monotonic() - start) * 1000
        return AIResponse(
            success=False,
            provider="gemini",
            model=model,
            latency_ms=latency_ms,
            attempt_count=max_retries + 1,
            error=last_error,
        )

    def _real_gemini_call(self, prompt, model, temperature, max_tokens, timeout):
        """Real Gemini API call using google-genai SDK."""
        try:
            from google import genai
            from google.genai import types

            # Gemini 2.5 models spend part of max_output_tokens on internal
            # "thinking" before writing the visible response. For a
            # deterministic extraction task (no multi-step reasoning needed),
            # that budget is wasted and can silently truncate the JSON output.
            # Disabling it (thinking_budget=0) keeps the full token budget
            # available for the actual response.
            thinking_budget = self.config.get("thinking_budget", 0)

            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
                ),
            )
            text = response.text
            return True, text, None
        except Exception as e:
            return False, "", self._clean_error(str(e))

    def _try_parse_json(self, text: str) -> Optional[dict]:
        """
        Try to parse JSON. If it fails (e.g. truncated response), attempt to
        salvage whatever complete invoice objects were written before truncation.
        Returns a valid schema dict, or None if nothing could be salvaged.
        """
        if not text:
            return None

        # Step 1: Try normal parse first (handles complete responses)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        # Step 2: Try to extract from markdown code fence
        import re
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass

        # Step 3: Salvage — extract complete invoice objects from truncated JSON.
        # This handles the case where Gemini's response is cut off mid-object
        # because the full JSON exceeded the output token limit.
        # We find the "invoices" array and extract every complete object from it.
        return self._salvage_invoices_from_truncated_json(text)

    def _salvage_invoices_from_truncated_json(self, text: str) -> Optional[dict]:
        """
        Extract complete invoice objects from a truncated JSON response.

        Strategy:
        1. Find the "invoices": [ array in the response
        2. Extract complete {...} objects from it (those that end with })
        3. Build a minimal valid schema dict with the salvaged invoices
        4. Extract whatever metadata fields we can from the beginning of the response

        Returns a schema dict with salvaged invoices, or None if nothing found.
        """
        import json

        if '"invoices"' not in text:
            return None

        # Extract the invoices array portion
        invoices_start = text.find('"invoices"')
        if invoices_start == -1:
            return None

        # Find the opening [ of the invoices array
        array_start = text.find('[', invoices_start)
        if array_start == -1:
            return None

        invoices_text = text[array_start:]

        # Extract complete invoice objects using brace counting
        salvaged_invoices = []
        i = 0
        while i < len(invoices_text):
            if invoices_text[i] == '{':
                # Found start of an object — find its matching closing brace
                depth = 0
                start = i
                in_string = False
                escape_next = False
                j = i
                while j < len(invoices_text):
                    c = invoices_text[j]
                    if escape_next:
                        escape_next = False
                    elif c == '\\' and in_string:
                        escape_next = True
                    elif c == '"':
                        in_string = not in_string
                    elif not in_string:
                        if c == '{':
                            depth += 1
                        elif c == '}':
                            depth -= 1
                            if depth == 0:
                                # Found a complete object
                                obj_text = invoices_text[start:j+1]
                                try:
                                    obj = json.loads(obj_text)
                                    # Only include if it looks like an invoice
                                    if isinstance(obj, dict) and (
                                        obj.get('invoice_number') or
                                        obj.get('outstanding_amount') or
                                        obj.get('amount')
                                    ):
                                        salvaged_invoices.append(obj)
                                except (json.JSONDecodeError, TypeError):
                                    pass
                                i = j + 1
                                break
                    j += 1
                else:
                    # No matching closing brace found — we've hit the truncation point
                    break
            elif invoices_text[i] == ']':
                # End of invoices array
                break
            i += 1

        if not salvaged_invoices:
            return None

        # Try to salvage metadata from the beginning of the response
        metadata = self._salvage_metadata(text)

        print(f"  [GeminiClient] Salvaged {len(salvaged_invoices)} complete invoice objects "
              f"from truncated JSON response")

        return {
            "document_metadata": metadata.get("document_metadata", {
                "document_type": "VENDOR_STATEMENT",
                "source_file": "",
                "page_count": 0,
                "document_type_confidence": 0.85,
            }),
            "vendor_metadata": metadata.get("vendor_metadata", {
                "vendor_name": None,
                "vendor_address": None,
                "shop_or_entity": [],
                "vendor_confidence": None,
            }),
            "statement_metadata": metadata.get("statement_metadata", {
                "statement_date": None,
                "statement_period_start": None,
                "statement_period_end": None,
                "currency": "USD",
                "statement_total_as_printed": None,
                "statement_confidence": None,
            }),
            "invoices": salvaged_invoices,
            "extraction_confidence": {
                "overall": 0.80,  # slightly lower confidence for salvaged response
                "table_detection_confidence": 0.85,
                "column_mapping_confidence": 0.80,
            },
            "warnings": [{
                "code": "OTHER",
                "message": f"Response truncated — salvaged {len(salvaged_invoices)} of possible more invoices. "
                           f"Later invoices in the statement may be missing.",
                "severity": "MEDIUM",
            }],
            "_salvaged": True,
        }

    def _salvage_metadata(self, text: str) -> dict:
        """
        Try to extract document/vendor/statement metadata from the beginning
        of a truncated JSON response. Best-effort — returns empty dict if nothing found.
        """
        import json

        result = {}

        for section in ["document_metadata", "vendor_metadata", "statement_metadata"]:
            try:
                key = f'"{section}"'
                start = text.find(key)
                if start == -1:
                    continue
                obj_start = text.find('{', start)
                if obj_start == -1:
                    continue
                # Find matching closing brace
                depth = 0
                in_string = False
                escape_next = False
                for i in range(obj_start, min(obj_start + 2000, len(text))):
                    c = text[i]
                    if escape_next:
                        escape_next = False
                    elif c == '\\' and in_string:
                        escape_next = True
                    elif c == '"':
                        in_string = not in_string
                    elif not in_string:
                        if c == '{':
                            depth += 1
                        elif c == '}':
                            depth -= 1
                            if depth == 0:
                                obj = json.loads(text[obj_start:i+1])
                                result[section] = obj
                                break
            except Exception:
                pass

        return result

    def _clean_error(self, raw_error: str) -> str:
        """
        Convert a raw Gemini API error into a short, readable message.
        Instead of the full JSON error dump, return one line.
        """
        if not raw_error:
            return "unknown error"

        raw = str(raw_error)

        # Quota / rate limit
        if "RESOURCE_EXHAUSTED" in raw or "quota" in raw.lower():
            # Try to extract retry delay
            import re
            delay_match = re.search(r"retryDelay['\"]:\s*['\"](\d+)s", raw)
            delay = f" (retry in {delay_match.group(1)}s)" if delay_match else ""
            return f"quota exhausted{delay}"

        # Auth / API key issues
        if "API_KEY_INVALID" in raw or "invalid api key" in raw.lower():
            return "invalid API key"

        if "PERMISSION_DENIED" in raw:
            return "permission denied — check API key"

        # Network / timeout
        if "timeout" in raw.lower() or "timed out" in raw.lower():
            return "request timed out"

        if "connection" in raw.lower() or "network" in raw.lower():
            return "network error"

        # Safety / content filter
        if "SAFETY" in raw or "safety" in raw.lower():
            return "blocked by safety filter"

        # Generic — just return first 100 chars, no JSON dump
        first_line = raw.split('\n')[0][:100]
        return first_line

    def generate_with_file(self, pdf_path: str, prompt: str) -> AIResponse:
        """
        Send a PDF file directly to Gemini using inline base64 encoding.
        Used for scanned PDFs where pdfplumber extracts no text.

        This uses Gemini's multimodal capability — it can read the PDF
        as an image and extract structured data from it directly.
        """
        import base64
        import time

        model = self.config["model"]
        temperature = self.config.get("temperature", 0.1)
        max_tokens = self.config.get("max_output_tokens", 65536)
        retry_policy = self.config.get("retry_policy", {})
        max_retries = retry_policy.get("max_retries", 2)
        backoff = retry_policy.get("backoff_seconds", 2)
        multiplier = retry_policy.get("backoff_multiplier", 2)

        if not self.api_key:
            return AIResponse(
                success=False, provider="gemini", model=model,
                error=f"Missing API key — env var '{self.config.get('api_key_env_var')}' not set"
            )

        # Read and encode PDF
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

        start = time.monotonic()
        last_error = None

        for attempt in range(1, max_retries + 2):
            try:
                if self._transport:
                    success, text, error = self._transport(prompt, self.config)
                else:
                    success, text, error = self._real_gemini_file_call(
                        pdf_b64, prompt, model, temperature, max_tokens
                    )
                latency_ms = (time.monotonic() - start) * 1000

                if success:
                    parsed = self._try_parse_json(text)
                    return AIResponse(
                        success=True, text=text, parsed_json=parsed,
                        model=model, provider="gemini",
                        latency_ms=latency_ms, attempt_count=attempt,
                    )
                else:
                    last_error = error
                    if attempt <= max_retries:
                        time.sleep(backoff * (multiplier ** (attempt - 1)))
            except Exception as e:
                last_error = str(e)
                if attempt <= max_retries:
                    time.sleep(backoff * (multiplier ** (attempt - 1)))

        latency_ms = (time.monotonic() - start) * 1000
        return AIResponse(
            success=False, provider="gemini", model=model,
            latency_ms=latency_ms, attempt_count=max_retries + 1,
            error=last_error,
        )

    def _real_gemini_file_call(self, pdf_b64: str, prompt: str,
                                model: str, temperature: float, max_tokens: int):
        """Gemini API call with inline base64 PDF (multimodal)."""
        try:
            import base64
            from google import genai
            from google.genai import types

            thinking_budget = self.config.get("thinking_budget", 0)

            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(
                        data=base64.standard_b64decode(pdf_b64),
                        mime_type="application/pdf",
                    ),
                    types.Part.from_text(text=prompt),
                ],
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
                ),
            )
            return True, response.text, None
        except Exception as e:
            return False, "", self._clean_error(str(e))
