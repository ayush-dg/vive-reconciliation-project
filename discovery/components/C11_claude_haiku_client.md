## C11 — Claude Haiku 4.5 Client
ID: M-026
Layer: pipeline
Source file: `src/ai/claude_client.py`

**Module** — Claude Haiku 4.5 Client
**ID** — M-026
**Layer** — pipeline
**Primary Responsibility** — Used exclusively by the Explanation Service (M-033) for exception narrative generation — the only file that knows Anthropic's SDK/wire format for this provider, routed via Azure Foundry.

**Inputs** — `config` (`config/ai/claude.json`); env vars `ANTHROPIC_API_KEY`/`AZURE_CLAUDE_ENDPOINT`/`AZURE_CLAUDE_DEPLOYMENT`.

**Outputs** — `AIResponse` — text completion (`generate()`) or file-based extraction (`generate_with_file()`, present for interface completeness but not the path M-033 uses).

**Public Interface** — `ClaudeClient(config, transport=None)`, `.generate()`, `.generate_with_file()`.

**Error Behaviour** — Never raises; missing API key returns a clean failed `AIResponse` immediately (no retry). Retries `max_retries` times with backoff on real API failures. Truncated JSON responses are salvaged via brace-counting (`_salvage_invoices_from_truncated_json()`), returning partial results rather than nothing.

**Known Fragility** — This client's truncation-salvage logic targets an `"invoices"` array shape — a different response shape than M-025/M-029's `"rows"`-keyed salvage logic. Since this client is only ever used for the (differently-shaped) exception-explanation JSON via `generate()`, the `"invoices"`-shaped salvage path in `_try_parse_json()`/`generate_with_file()` is realistically unreachable from this codebase's actual usage — dead-but-plausible code that could mislead a reader into thinking this client is used for document extraction.

**Change Impact** — Isolated to M-033's explanation flow; does not affect the document-extraction chain at all (independent of `active_provider.json`).

**Callers** — M-023 (`get_ai_client("claude")`, instantiation — called by M-033)
**Calls** — none
**Integration Points Used** — IP-002 (Claude Haiku 4.5, Azure AI Foundry)
