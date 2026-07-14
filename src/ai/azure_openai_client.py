"""
azure_openai_client.py

Azure OpenAI implementation of AIClient. The ONLY file that knows Azure
OpenAI's SDK/wire format (Responses API).

One class, three deployments: gpt-5-mini, gpt-5-nano, gpt-5.1 are all
just different config/ai/azure_*.json files pointing at this same class
(see config's "deployment_env_var"), not three separate client classes.

Key Responses-API quirks this client works around (confirmed by direct
testing against the live endpoint, not assumed from GPT-4o-era docs):
  - These are reasoning models — the `temperature` parameter is REJECTED
    with a 400 if sent at all. generate()/generate_with_file() accept a
    temperature arg for AIClient interface parity but never forward it.
  - Reasoning tokens are drawn from the same max_output_tokens budget as
    the visible answer. A too-low cap can leave the response `status ==
    "incomplete"` with zero output text and only a reasoning item back —
    this looks like an empty success unless checked explicitly, so we
    treat it as a failure with a clear "raise max_output_tokens" error.
  - Direct base64 PDF input works today via `input_file` content blocks
    (input_type "input_file" + a `data:application/pdf;base64,...` URI),
    on the same api-version already used elsewhere in this project
    (2025-04-01-preview) — no need for the newer /openai/v1/ surface.
  - For scanned pages (no text layer), sending the raw PDF and relying on
    Azure's own internal, undocumented PDF-to-image conversion produced real
    invoice-number corruption (wrong prefixes, transposed digits, merged
    rows) in testing — see RULES.md RULE-04. generate_with_file() now
    detects pages with no extractable text and rasterizes them itself at
    SCANNED_PAGE_DPI via pdf2image, sending an `input_image` block instead
    so we control resolution directly rather than trusting an opaque
    server-side default. Text-layer pages are still sent as raw PDF
    (`input_file`) — that path already gave exact, high-fidelity results.
"""

import json
import os
import time
from typing import Callable, Optional

from .base_client import AIClient, AIResponse

# DPI used to rasterize scanned (no-text-layer) pages before sending as an
# input_image block. 300 was chosen after 65/69 rows extracted correctly at
# whatever (uncontrolled) resolution Azure's own internal PDF-to-image
# conversion used by default — bumping to a resolution we control directly
# is the fix, not a tuned/benchmarked optimum.
SCANNED_PAGE_DPI = 300


class AzureOpenAIClient(AIClient):
    def __init__(self, config: dict, transport: Optional[Callable] = None):
        """
        config   : parsed config/ai/azure_gpt5_*.json
        transport: optional injectable callable for testing.
                   Signature: (prompt, config) -> (success, text, error)
                   If None, uses the real Azure OpenAI (openai SDK) call.
        """
        self.config = config
        self._transport = transport

        self.api_key = os.environ.get(config.get("api_key_env_var", "AZURE_OPENAI_API_KEY"))
        self.endpoint = os.environ.get(config.get("endpoint_env_var", "AZURE_OPENAI_ENDPOINT"))
        self.deployment = os.environ.get(config.get("deployment_env_var", ""))
        self.api_version = config.get("api_version", "2025-04-01-preview")
        # Stashed by _extract_text_or_error() on the last real API call so
        # generate()/generate_with_file() can attach it as AIResponse.raw_response
        # (used by the model-comparison script to pull token usage for cost calc).
        self._last_raw_response = None

    def _missing_config_error(self) -> Optional[str]:
        if not self.api_key:
            return f"Missing API key — env var '{self.config.get('api_key_env_var')}' not set"
        if not self.endpoint:
            return f"Missing endpoint — env var '{self.config.get('endpoint_env_var')}' not set"
        if not self.deployment:
            return f"Missing deployment name — env var '{self.config.get('deployment_env_var')}' not set"
        return None

    def generate(self, prompt: str, *, temperature=None, max_output_tokens=None) -> AIResponse:
        # temperature is accepted for AIClient interface parity but never sent —
        # Azure rejects it outright for this reasoning-model family (see module docstring).
        model = self.deployment
        max_tokens = max_output_tokens or self.config.get("max_output_tokens", 65536)
        retry_policy = self.config.get("retry_policy", {})
        max_retries = retry_policy.get("max_retries", 2)
        backoff = retry_policy.get("backoff_seconds", 2)
        multiplier = retry_policy.get("backoff_multiplier", 2)

        missing = self._missing_config_error()
        if missing:
            return AIResponse(success=False, provider="azure_openai", model=model, error=missing)

        start = time.monotonic()
        last_error = None

        for attempt in range(1, max_retries + 2):
            try:
                if self._transport:
                    success, text, error = self._transport(prompt, self.config)
                else:
                    success, text, error = self._real_azure_call(prompt, model, max_tokens)

                latency_ms = (time.monotonic() - start) * 1000

                if success:
                    parsed = self._try_parse_json(text)
                    return AIResponse(
                        success=True,
                        text=text,
                        parsed_json=parsed,
                        model=model,
                        provider="azure_openai",
                        latency_ms=latency_ms,
                        attempt_count=attempt,
                        raw_response=self._last_raw_response,
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
            provider="azure_openai",
            model=model,
            latency_ms=latency_ms,
            attempt_count=max_retries + 1,
            error=last_error,
        )

    def _real_azure_call(self, prompt, model, max_tokens):
        """Real Azure OpenAI Responses API call, text-only input."""
        try:
            from openai import AzureOpenAI

            client = AzureOpenAI(
                azure_endpoint=self.endpoint,
                api_key=self.api_key,
                api_version=self.api_version,
                timeout=self.config.get("timeout_seconds", 90),
                # The SDK's own built-in retry (default 2) would silently compound
                # with AzureOpenAIClient's own outer retry loop — e.g. a 90s
                # per-call timeout would actually take up to 3x90s before this
                # method's caller ever sees an exception. Retries are handled
                # exactly once, at the AzureOpenAIClient level.
                max_retries=0,
            )
            kwargs = {
                "model": model,
                "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                "max_output_tokens": max_tokens,
            }
            reasoning_effort = self.config.get("reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning"] = {"effort": reasoning_effort}

            response = client.responses.create(**kwargs)
            return self._extract_text_or_error(response)
        except Exception as e:
            return False, "", self._clean_error(str(e))

    def _extract_text_or_error(self, response):
        """Shared response handling for both text-only and file calls."""
        self._last_raw_response = response
        if getattr(response, "status", None) == "incomplete":
            reason = getattr(response.incomplete_details, "reason", "unknown reason") \
                if response.incomplete_details else "unknown reason"
            return False, "", f"response incomplete ({reason}) — try raising max_output_tokens"
        return True, response.output_text, None

    def _try_parse_json(self, text: str) -> Optional[dict]:
        """
        Try to parse JSON. If it fails (e.g. truncated response), attempt to
        salvage whatever complete invoice objects were written before truncation.
        Returns a valid schema dict, or None if nothing could be salvaged.
        """
        if not text:
            return None

        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        import re
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass

        return self._salvage_invoices_from_truncated_json(text)

    def _salvage_invoices_from_truncated_json(self, text: str) -> Optional[dict]:
        """
        Extract complete invoice objects from a truncated JSON response.
        Same brace-counting strategy as ClaudeClient — kept duplicated here
        (rather than shared) since each provider file is self-contained and
        owns its own wire-format handling end to end.
        """
        import json

        if '"invoices"' not in text:
            return None

        invoices_start = text.find('"invoices"')
        if invoices_start == -1:
            return None

        array_start = text.find('[', invoices_start)
        if array_start == -1:
            return None

        invoices_text = text[array_start:]

        salvaged_invoices = []
        i = 0
        while i < len(invoices_text):
            if invoices_text[i] == '{':
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
                                obj_text = invoices_text[start:j + 1]
                                try:
                                    obj = json.loads(obj_text)
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
                    break
            elif invoices_text[i] == ']':
                break
            i += 1

        if not salvaged_invoices:
            return None

        metadata = self._salvage_metadata(text)

        print(f"  [AzureOpenAIClient] Salvaged {len(salvaged_invoices)} complete invoice objects "
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
                "overall": 0.80,
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
        """Best-effort metadata salvage from the head of a truncated JSON response."""
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
                                obj = json.loads(text[obj_start:i + 1])
                                result[section] = obj
                                break
            except Exception:
                pass

        return result

    def _clean_error(self, raw_error: str) -> str:
        """Convert a raw Azure/OpenAI SDK error into a short, readable message."""
        if not raw_error:
            return "unknown error"

        raw = str(raw_error)
        raw_lower = raw.lower()

        if "rate_limit" in raw_lower or "429" in raw:
            return "rate limited — try again shortly"

        if "authentication" in raw_lower or "401" in raw or "invalid api key" in raw_lower:
            return "invalid API key"

        if "permission" in raw_lower or "403" in raw:
            return "permission denied — check API key / deployment access"

        if "unsupported parameter" in raw_lower:
            return f"unsupported parameter for this deployment: {raw.split(chr(10))[0][:150]}"

        if "404" in raw or "deploymentnotfound" in raw_lower.replace(" ", ""):
            return "deployment not found — check deployment name / env var"

        if "timeout" in raw_lower or "timed out" in raw_lower:
            return "request timed out"

        if "connection" in raw_lower or "network" in raw_lower:
            return "network error"

        first_line = raw.split('\n')[0][:150]
        return first_line

    def _page_has_text_layer(self, pdf_path: str) -> bool:
        """
        True if the PDF's first page has a real, substantial text layer.
        A short/empty result means it's scanned (image-only) — anything
        below this length is treated as "no usable text" rather than a
        partial/thin layer worth trusting.
        """
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                text = (pdf.pages[0].extract_text() or "").strip()
                return len(text) > 20
        except Exception:
            # If we can't even open/read it, fall through to the existing
            # raw-PDF path rather than guessing at rasterization.
            return True

    def _build_document_content_block(self, pdf_path: str, filename: str) -> dict:
        """
        Build the Responses API content block for a single-page PDF.

        Text-layer pages are sent as-is (`input_file`, exact text preserved —
        this path already produced exact, high-fidelity results in testing).
        Scanned pages (no text layer) are rasterized locally at
        SCANNED_PAGE_DPI via pdf2image and sent as `input_image` instead of
        `input_file` — giving us control over resolution rather than relying
        on Azure's own opaque server-side PDF-to-image conversion, which was
        found to produce systematic invoice-number corruption on a real
        scanned document (see RULES.md RULE-04).
        """
        import base64

        if self._page_has_text_layer(pdf_path):
            with open(pdf_path, "rb") as f:
                pdf_b64 = base64.standard_b64encode(f.read()).decode("utf-8")
            return {
                "type": "input_file",
                "filename": filename,
                "file_data": f"data:application/pdf;base64,{pdf_b64}",
            }

        import io
        from pdf2image import convert_from_path

        images = convert_from_path(pdf_path, dpi=SCANNED_PAGE_DPI)
        buf = io.BytesIO()
        images[0].save(buf, format="PNG")
        img_b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
        return {
            "type": "input_image",
            "image_url": f"data:image/png;base64,{img_b64}",
        }

    def generate_with_file(self, pdf_path: str, prompt: str) -> AIResponse:
        """
        Send a PDF file to the model via the Responses API. Text-layer PDFs
        go through as an inline base64 `input_file` block (exact text
        preserved); scanned pages are rasterized locally at SCANNED_PAGE_DPI
        and sent as `input_image` instead (see _build_document_content_block).
        Confirmed working for gpt-5-mini, gpt-5-nano, and gpt-5.1 by direct
        testing against the live endpoint.
        """
        model = self.deployment
        max_tokens = self.config.get("max_output_tokens", 65536)
        retry_policy = self.config.get("retry_policy", {})
        max_retries = retry_policy.get("max_retries", 2)
        backoff = retry_policy.get("backoff_seconds", 2)
        multiplier = retry_policy.get("backoff_multiplier", 2)

        missing = self._missing_config_error()
        if missing:
            return AIResponse(success=False, provider="azure_openai", model=model, error=missing)

        filename = os.path.basename(pdf_path)
        content_block = self._build_document_content_block(pdf_path, filename)

        start = time.monotonic()
        last_error = None

        for attempt in range(1, max_retries + 2):
            try:
                if self._transport:
                    success, text, error = self._transport(prompt, self.config)
                else:
                    success, text, error = self._real_azure_file_call(
                        content_block, prompt, model, max_tokens
                    )
                latency_ms = (time.monotonic() - start) * 1000

                if success:
                    parsed = self._try_parse_json(text)
                    return AIResponse(
                        success=True, text=text, parsed_json=parsed,
                        model=model, provider="azure_openai",
                        latency_ms=latency_ms, attempt_count=attempt,
                        raw_response=self._last_raw_response,
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
            success=False, provider="azure_openai", model=model,
            latency_ms=latency_ms, attempt_count=max_retries + 1,
            error=last_error,
        )

    def _real_azure_file_call(self, content_block: dict, prompt: str,
                               model: str, max_tokens: int):
        """Azure OpenAI Responses API call with a pre-built document content
        block (either `input_file` for text-layer PDFs or `input_image` for
        rasterized scanned pages — see _build_document_content_block)."""
        try:
            from openai import AzureOpenAI

            client = AzureOpenAI(
                azure_endpoint=self.endpoint,
                api_key=self.api_key,
                api_version=self.api_version,
                timeout=self.config.get("timeout_seconds", 90),
                # The SDK's own built-in retry (default 2) would silently compound
                # with AzureOpenAIClient's own outer retry loop — e.g. a 90s
                # per-call timeout would actually take up to 3x90s before this
                # method's caller ever sees an exception. Retries are handled
                # exactly once, at the AzureOpenAIClient level.
                max_retries=0,
            )
            kwargs = {
                "model": model,
                "input": [{
                    "role": "user",
                    "content": [
                        content_block,
                        {"type": "input_text", "text": prompt},
                    ],
                }],
                "max_output_tokens": max_tokens,
            }
            reasoning_effort = self.config.get("reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning"] = {"effort": reasoning_effort}

            response = client.responses.create(**kwargs)
            return self._extract_text_or_error(response)
        except Exception as e:
            return False, "", self._clean_error(str(e))
