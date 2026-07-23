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

    elif provider_name == "mistral":
        # Mistral Medium via the direct Mistral API — registered but not
        # part of the default active chain (claude_sonnet is primary — see
        # below). See mistral_client.py for why per-page rasterization is
        # required (Mistral rejects raw PDF data URIs).
        from .mistral_client import MistralClient
        config = _load_json(config_paths.get("mistral", "config/ai/mistral.json"))
        return MistralClient(config)

    elif provider_name == "claude_sonnet":
        # Active primary — Claude Sonnet 4.6 via Azure Foundry (streaming).
        # Sends the whole PDF as one base64 document block + one streaming
        # messages call (no page splitting). See claude_sonnet_client.py.
        # [Corrected 2026-07-24, BCE Stage 3 documentation sweep — this
        # comment previously said "gemini is primary"; confirmed false
        # against active_provider.json's provider_chain.]
        from .claude_sonnet_client import ClaudeSonnetClient
        config = _load_json(config_paths.get("claude_sonnet", "config/ai/claude_sonnet_extraction.json"))
        return ClaudeSonnetClient(config)

    elif provider_name == "gemini":
        # Gemini 2.5 Flash via the google-genai SDK — registered as an
        # alternate extraction provider, NOT part of the active chain
        # (claude_sonnet is primary — see above). Sends the whole PDF as
        # one file upload + one generate_content call (no page splitting
        # needed). See gemini_client.py for the column-agnostic mapping
        # approach and why it handles multi-invoice-column vendors (e.g.
        # Fred_Beans_MidNJ_053126.pdf) better than picking by header order.
        # [Corrected 2026-07-24, BCE Stage 3 documentation sweep — this
        # comment previously said "Active primary"; confirmed false.]
        from .gemini_client import GeminiClient
        config = _load_json(config_paths.get("gemini", "config/ai/gemini.json"))
        return GeminiClient(config)

    elif provider_name in ("azure_gpt5_mini", "azure_gpt5_nano", "azure_gpt5_1"):
        # No longer the active chain (see RULES.md RULE-04 — superseded by
        # azure_doc_intel, then by claude_sonnet); configs are kept
        # registered for direct get_ai_client() access pending a separate
        # cleanup pass. One shared client class, config-parameterized per
        # deployment; see azure_openai_client.py.
        from .azure_openai_client import AzureOpenAIClient
        default_path = f"config/ai/{provider_name}.json"
        config = _load_json(config_paths.get(provider_name, default_path))
        return AzureOpenAIClient(config)

    elif provider_name == "azure_doc_intel":
        # No longer the active primary (superseded by claude_sonnet, see
        # RULES.md RULE-04 — briefly by gemini in between, per that rule's
        # history); registered for direct get_ai_client() access. Azure
        # Document Intelligence prebuilt-layout. See document_intelligence_client.py.
        # [Corrected 2026-07-24, BCE Stage 3 documentation sweep — this
        # comment previously said "superseded by gemini"; the actual
        # current primary is claude_sonnet.]
        from .document_intelligence_client import DocumentIntelligenceClient
        config = _load_json(config_paths.get("azure_doc_intel", "config/ai/azure_doc_intel.json"))
        return DocumentIntelligenceClient(config)

    else:
        raise ValueError(f"Unknown provider: '{provider_name}'. Add it to client_factory.py.")


def get_provider_chain() -> list:
    """Returns the full ordered provider chain from config."""
    active_config_path = "config/ai/active_provider.json"
    active_config = _load_json(active_config_path)
    return active_config.get("provider_chain", ["azure_gpt5_mini", "pdfplumber"])
