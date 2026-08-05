## C08 — AI Client Factory
ID: M-023
Layer: pipeline
Source file: `src/ai/client_factory.py`

**Module** — AI Client Factory
**ID** — M-023
**Layer** — pipeline
**Primary Responsibility** — The only place that reads `config/ai/active_provider.json` and instantiates a concrete `AIClient`; every other module calls `get_ai_client()` and never imports a provider class directly.

**Inputs** — `provider_name` (optional; defaults to `active_provider.json`'s `provider_chain[0]`), `config/ai/active_provider.json`, per-provider config files.

**Outputs** — A concrete `AIClient` instance (M-025–M-030).

**Public Interface** — `get_ai_client(provider_name=None) -> AIClient`, `get_provider_chain() -> list`.

**Error Behaviour** — Raises `ValueError` for an unrecognized `provider_name` (a genuine programming error, not a runtime/network condition) — this is the one place in the AI layer that raises rather than returning a failed `AIResponse`, since it's a config/code mismatch, not an extraction failure.

**Known Fragility** — Every provider's inline comment here has been individually corrected at least once for staleness (documented via `[Corrected 2026-07-24, BCE Stage 3 documentation sweep]` markers directly in the source, confirmed still present and accurate this session) — this file's comments are a known historical hotspot for provider-primacy claims drifting from `active_provider.json`'s actual `provider_chain`; any future provider swap should update the comment in the same commit, not after.

**Change Impact** — The single chokepoint for which AI provider the entire extraction pipeline uses — a change to the default resolution logic (or to `active_provider.json` itself) changes which of IP-001 through IP-006 every extraction call reaches, system-wide.

**Callers** — M-024 (`get_ai_client()`), M-033 (`get_ai_client("claude")`), M-044 (`get_ai_client`, `get_provider_chain`)
**Calls** — M-025, M-026, M-027, M-028, M-029, M-030 (lazy per-branch instantiation)
**Integration Points Used** — none directly (selects which downstream module reaches IP-001–IP-006)
