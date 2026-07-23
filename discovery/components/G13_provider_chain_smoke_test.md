## G13 — provider-chain smoke test
ID: M-040
Layer: infra
Source file: scripts/test_provider_chain.py

**Module** — provider-chain smoke test
**ID** — M-040
**Layer** — infra
**Primary Responsibility** — Meets the BCE-009 module-worthiness bar (makes real, traceable calls into a registered module — `client_factory.get_ai_client()` — as its primary mechanism, not merely asserting against a modeled module). Prints the resolved provider chain and confirms each provider's client loads with a valid config.

**Inputs** — None (no CLI args).

**Outputs** — Console output only: the resolved `provider_chain` list, and per-provider `client loaded OK — model=...` or `ERROR — ...` lines.

**Public Interface** — None (script-only, top-level code, not a function-wrapped module).

**Error Behaviour** — Wraps each provider's `get_ai_client(provider)` call in its own `try/except Exception as e`, printing the error inline and continuing to the next provider — one bad provider config does not stop the smoke test from checking the rest.

**Known Fragility** — This only confirms client *instantiation* succeeds (config loads, required env vars are read) — it does not make a real API call to any provider, so it cannot catch an invalid/expired API key, only a missing one (via each client's `_missing_config_error()` check).

**Change Impact** — None — pure diagnostic script, not imported anywhere.

**Callers** — none (invoked directly, `python scripts/test_provider_chain.py`)
**Calls** — M-031 (`get_ai_client`, `get_provider_chain`)
**Integration Points Used** — none directly (would exercise IP-001/002/003/004/005/006 if any provider's real API were actually called, which it is not)
