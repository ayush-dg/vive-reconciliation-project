## G08 — Provider Chain Smoke Test
ID: M-044
Layer: infra
Source file: `scripts/test_provider_chain.py`

**Module** — Provider Chain Smoke Test
**ID** — M-044
**Layer** — infra
**Primary Responsibility** — Standalone diagnostic script: prints the resolved provider chain from config and confirms each provider's client loads (instantiates) without error.

**Inputs** — `config/ai/active_provider.json` (via M-023).

**Outputs** — Stdout only; no database or filesystem writes.

**Public Interface** — None exported; script-only, run directly (`python scripts/test_provider_chain.py`).

**Error Behaviour** — Wraps each provider's client instantiation in its own `try/except`, printing `ERROR — {e}` for that provider and continuing to the next — one broken provider config doesn't stop the script from checking the rest.

**Known Fragility** — Only verifies that a client *instantiates* (constructor succeeds) — does not verify it can actually reach its provider (no real network call made). A provider with valid-looking config but a revoked/expired API key would still print "client loaded OK."

**Change Impact** — None — diagnostic-only, not called by any runtime code.

**Callers** — none (developer-invoked)
**Calls** — M-023 (`get_ai_client`, `get_provider_chain`)
**Integration Points Used** — none directly (does not make a real call to any IP-NNN)
