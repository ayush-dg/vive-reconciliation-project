"""
groq_client.py

Groq (llama-3.3-70b-versatile) implementation of AIClient.
Free tier: 14,400 requests/day — used as fallback when Gemini fails.
"""

import json
import os
import time
from typing import Callable, Optional

from .base_client import AIClient, AIResponse


class GroqClient(AIClient):
    def __init__(self, config: dict, transport: Optional[Callable] = None):
        self.config = config
        self._transport = transport

        api_key_var = config.get("api_key_env_var", "GROQ_API_KEY")
        self.api_key = os.environ.get(api_key_var)

    def generate(self, prompt: str, *, temperature=None, max_output_tokens=None) -> AIResponse:
        model = self.config["model"]
        temperature = temperature if temperature is not None else self.config.get("temperature", 0.1)
        max_tokens = max_output_tokens or self.config.get("max_output_tokens", 8192)
        retry_policy = self.config.get("retry_policy", {})
        max_retries = retry_policy.get("max_retries", 2)
        backoff = retry_policy.get("backoff_seconds", 1)
        multiplier = retry_policy.get("backoff_multiplier", 2)

        if not self.api_key:
            return AIResponse(
                success=False,
                provider="groq",
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
                    success, text, error = self._real_groq_call(
                        prompt, model, temperature, max_tokens
                    )

                latency_ms = (time.monotonic() - start) * 1000

                if success:
                    parsed = self._try_parse_json(text)
                    return AIResponse(
                        success=True,
                        text=text,
                        parsed_json=parsed,
                        model=model,
                        provider="groq",
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
            provider="groq",
            model=model,
            latency_ms=latency_ms,
            attempt_count=max_retries + 1,
            error=last_error,
        )

    def _real_groq_call(self, prompt, model, temperature, max_tokens):
        try:
            from groq import Groq
            client = Groq(api_key=self.api_key)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            text = response.choices[0].message.content
            return True, text, None
        except Exception as e:
            return False, "", self._clean_error(str(e))

    def _try_parse_json(self, text: str) -> Optional[dict]:
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            import re
            match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
            if match:
                try:
                    return json.loads(match.group(1))
                except Exception:
                    pass
            return None

    def _clean_error(self, raw_error: str) -> str:
        """Convert a raw Groq API error into a short, readable message."""
        if not raw_error:
            return "unknown error"

        raw = str(raw_error)

        # Token limit
        if "413" in raw or "Request too large" in raw or "TPM" in raw:
            import re
            requested = re.search(r"Requested (\d+)", raw)
            limit = re.search(r"Limit (\d+)", raw)
            if requested and limit:
                return f"request too large ({requested.group(1)} tokens requested, {limit.group(1)} limit)"
            return "request too large for token limit"

        # Rate limit
        if "429" in raw or "rate_limit" in raw.lower() or "rate limit" in raw.lower():
            return "rate limited — try again shortly"

        # Auth
        if "401" in raw or "invalid_api_key" in raw.lower():
            return "invalid API key"

        # Timeout
        if "timeout" in raw.lower():
            return "request timed out"

        # Generic
        first_line = raw.split('\n')[0][:100]
        return first_line
