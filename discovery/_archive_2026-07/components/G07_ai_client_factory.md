## G07 — AI client factory
ID: M-031
Layer: infra
Source file: src/ai/client_factory.py

**Module** — AI client factory
**ID** — M-031
**Layer** — infra
**Primary Responsibility** — The only module that reads `config/ai/active_provider.json` and instantiates concrete AI provider clients; every caller depends on `AIClient`, never a concrete class.

**Inputs** — `get_ai_client(provider_name: Optional[str] = None)`: if `None`, resolves `provider_chain[0]` from `active_provider.json`. `get_provider_chain()`: no inputs.

**Outputs** — A concrete `AIClient` subclass instance, config-loaded from the matching `config/ai/*.json` file.

**Public Interface**
- `get_ai_client(provider_name: Optional[str] = None) -> AIClient`
- `get_provider_chain() -> list`
- `_load_json(path: str) -> dict` (private)

**Error Behaviour** — `get_ai_client()` raises `ValueError` for an unrecognized `provider_name` ("Unknown provider... Add it to client_factory.py") — a deliberate fail-loud for a genuine configuration bug, not swallowed. No handling around `_load_json()` itself — a missing/malformed `active_provider.json` or provider config file raises `FileNotFoundError`/`JSONDecodeError` uncaught.

**Known Fragility**
- **This module's own inline comments are stale and self-contradictory relative to the file it reads** — confirmed by direct comparison during Session A: the comment above the `"gemini"` branch (line ~61-66) reads "Active primary — Gemini 2.5 Flash," and the comment above `"claude_sonnet"` (line ~52-55) reads "registered as an alternate extraction provider, not part of the active chain (gemini is primary)" — but `active_provider.json`'s actual `provider_chain[0]` is `"claude_sonnet"`, not `"gemini"`. This is the single clearest instance of the AI-provider-chain divergence documented in TOPOLOGY.md/A02 — the file that *authoritatively resolves* the active provider has comments describing a different, stale state.
- `_load_json()` re-reads and re-parses `active_provider.json` from disk on every single `get_ai_client()`/`get_provider_chain()` call — no caching. Low practical cost (small file) but worth noting for a high-call-volume future.

**Change Impact** — Adding a new provider requires: a new `config/ai/*.json` file, a new `elif` branch here, and a new concrete client class — three coordinated changes, no single point of registration.

**Callers** — M-020 (`document_understanding_engine.py`), M-029 (`explanation_service.py`, hardcoded `"claude"`), M-040 (`scripts/test_provider_chain.py`)
**Calls** — M-021, M-022, M-023, M-024, M-025, M-026 (conditionally, by `provider_name`)
**Integration Points Used** — none directly (delegates to whichever concrete client is instantiated)
