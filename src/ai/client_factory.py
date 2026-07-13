"""
client_factory.py

The only place that reads active_provider.json and instantiates
concrete AI clients. Every other module calls get_ai_client()
and gets back an AIClient — never a GeminiClient or GroqClient directly.
"""

import json
import os
from typing import Optional
from .base_client import AIClient


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_ai_client(provider_name: Optional[str] = None) -> AIClient:
    """
    Returns an AIClient for the given provider name.
    If provider_name is None, reads active_provider.json to find the first
    provider in the chain.

    The caller never needs to know whether it gets Gemini or Groq.
    """
    active_config_path = "config/ai/active_provider.json"
    active_config = _load_json(active_config_path)

    if provider_name is None:
        # Default: first in chain
        chain = active_config.get("provider_chain", ["gemini"])
        provider_name = chain[0]

    config_paths = active_config.get("provider_config_paths", {})

    if provider_name == "gemini":
        from .gemini_client import GeminiClient
        config = _load_json(config_paths.get("gemini", "config/ai/gemini.json"))
        return GeminiClient(config)

    elif provider_name == "groq":
        from .groq_client import GroqClient
        config = _load_json(config_paths.get("groq", "config/ai/groq.json"))
        return GroqClient(config)

    else:
        raise ValueError(f"Unknown provider: '{provider_name}'. Add it to client_factory.py.")


def get_provider_chain() -> list:
    """Returns the full ordered provider chain from config."""
    active_config_path = "config/ai/active_provider.json"
    active_config = _load_json(active_config_path)
    return active_config.get("provider_chain", ["gemini", "groq", "pdfplumber"])
