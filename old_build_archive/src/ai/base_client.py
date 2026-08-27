"""
base_client.py

The contract. Every AI provider adapter implements AIClient.
Nothing outside src/ai/ ever imports a concrete provider class directly —
they depend on this interface instead.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AIResponse:
    """Provider-neutral response. Every concrete client translates its
    wire format into this shape."""
    success: bool
    text: str = ""
    parsed_json: Optional[dict] = None
    model: str = ""
    provider: str = ""
    latency_ms: float = 0.0
    attempt_count: int = 1
    error: Optional[str] = None
    raw_response: Any = field(default=None, repr=False)


class AIClient(ABC):
    """
    Abstract AI client interface.
    One method: send a prompt, get a structured response back.
    """

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> AIResponse:
        raise NotImplementedError
