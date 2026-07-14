"""
client_factory.py

The only place that reads active_provider.json and instantiates
concrete AI clients. Every other module calls get_ai_client()
and gets back an AIClient — never a ClaudeClient directly.
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

    The caller never needs to know which concrete client it gets.
    """
    active_config_path = "config/ai/active_provider.json"
    active_config = _load_json(active_config_path)

    if provider_name is None:
        # Default: first in chain
        chain = active_config.get("provider_chain", ["azure_gpt5_mini"])
        provider_name = chain[0]

    config_paths = active_config.get("provider_config_paths", {})

    if provider_name == "claude":
        from .claude_client import ClaudeClient
        config = _load_json(config_paths.get("claude", "config/ai/claude.json"))
        return ClaudeClient(config)

    elif provider_name in ("azure_gpt5_mini", "azure_gpt5_nano", "azure_gpt5_1"):
        # azure_gpt5_mini is the active primary (see RULES.md RULE-04) after
        # winning a 3-model comparison; azure_gpt5_nano/azure_gpt5_1 configs
        # are kept registered for direct get_ai_client() access but are not
        # part of provider_chain. One shared client class, config-parameterized
        # per deployment; see azure_openai_client.py.
        from .azure_openai_client import AzureOpenAIClient
        default_path = f"config/ai/{provider_name}.json"
        config = _load_json(config_paths.get(provider_name, default_path))
        return AzureOpenAIClient(config)

    else:
        raise ValueError(f"Unknown provider: '{provider_name}'. Add it to client_factory.py.")


def get_provider_chain() -> list:
    """Returns the full ordered provider chain from config."""
    active_config_path = "config/ai/active_provider.json"
    active_config = _load_json(active_config_path)
    return active_config.get("provider_chain", ["azure_gpt5_mini", "pdfplumber"])
