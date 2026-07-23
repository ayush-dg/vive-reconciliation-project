## C09 — Claude (Haiku 4.5) client
ID: M-022
Layer: pipeline
Source file: src/ai/claude_client.py

**Module** — Claude (Haiku 4.5) client
**ID** — M-022
**Layer** — pipeline
**Primary Responsibility** — `AIClient` implementation for Claude Haiku 4.5 via Azure Foundry. Registered but not the active extraction primary — used exclusively by `ExplanationService` (M-029), hardcoded independent of `provider_chain`.

**Inputs** — `ClaudeClient(config: dict, transport: Optional[Callable] = None)`; `generate(prompt, ...)`; `generate_with_file(pdf_path, prompt)`.

**Outputs** — `AIResponse` — for `generate_with_file()`, `parsed_json` is the model's response **passed through unmodified** (`json.loads(text)`, no per-row remapping) — confirmed by source: this is one of only two clients (with M-021) that genuinely elicit and preserve model-reported `line_confidence`, rather than fabricating a constant.

**Public Interface**
- `generate(...) -> AIResponse`, `generate_with_file(pdf_path, prompt) -> AIResponse`
- Private: `_build_client()` (routes through `anthropic.AnthropicFoundry` when `AZURE_CLAUDE_ENDPOINT` is set, else direct `anthropic.Anthropic`), `_real_claude_call()`, `_real_claude_file_call()`, `_try_parse_json()`, `_salvage_invoices_from_truncated_json()`, `_salvage_metadata()`, `_clean_error()`

**Error Behaviour** — Standard retry-with-backoff loop (`max_retries` from config, default 2, exponential via `backoff_multiplier`) around both `generate()` and `generate_with_file()`. JSON truncation salvage identical in strategy to M-021's (brace-counting), independently implemented.

**Known Fragility** — **This is the client `EXPLANATION_PROVIDER = "claude"` in `explanation_service.py` resolves to** — its extraction capability (`generate_with_file`) is not exercised by that caller, only its plain-text `generate()`. Confirmed genuinely dormant for document extraction in the current live system (not reachable via the default provider chain), used only for its text-completion capability.

**Change Impact** — If ever restored as the active extraction primary, this is the client that would correctly honor `VISION_PROMPT` and preserve real per-row confidence — unlike M-023/M-025/M-026.

**Callers** — M-031 (conditionally, `provider_name == "claude"` — confirmed live caller: M-029's hardcoded `EXPLANATION_PROVIDER`)
**Calls** — none (leaf node; lazily imports `anthropic`)
**Integration Points Used** — IP-002 (Claude Haiku 4.5)
