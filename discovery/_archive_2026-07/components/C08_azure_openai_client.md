## C08 — Azure OpenAI client
ID: M-021
Layer: pipeline
Source file: src/ai/azure_openai_client.py

**Module** — Azure OpenAI client
**ID** — M-021
**Layer** — pipeline
**Primary Responsibility** — `AIClient` implementation for Azure OpenAI's Responses API (gpt-5-mini/nano/5.1, one class shared across all three deployments via config). Registered but **not in the active `provider_chain`** as of this session.

**Inputs** — `AzureOpenAIClient(config: dict, transport: Optional[Callable] = None)`; `generate(prompt, *, temperature=None, max_output_tokens=None)`; `generate_with_file(pdf_path, prompt)`.

**Outputs** — `AIResponse` with `parsed_json` following the Universal Financial Document Schema (via the passed `VISION_PROMPT` — this client is one of only two, alongside M-022, that actually honors the passed prompt rather than substituting its own).

**Public Interface**
- `generate(...) -> AIResponse`, `generate_with_file(pdf_path, prompt) -> AIResponse`
- Private: `_missing_config_error()`, `_real_azure_call()`, `_extract_text_or_error()`, `_try_parse_json()`, `_salvage_invoices_from_truncated_json()`, `_salvage_metadata()`, `_clean_error()`, `_page_has_text_layer()`, `_build_document_content_block()`, `_split_into_pages()`, `_process_single_page()`

**Error Behaviour**
- **Never forwards `temperature`** to the API — these are reasoning models that reject it with a 400; confirmed the parameter is accepted for interface parity only, never included in the request payload.
- **Detects the `status == "incomplete"` response shape explicitly** and converts it to a clean failure ("try raising max_output_tokens") rather than returning an apparently-successful empty response — a real, previously-encountered failure mode per the module docstring, confirmed handled in `_extract_text_or_error()`.
- **Per-page retry-once, not the outer retry_policy loop** — `_process_single_page()` retries a failed page exactly once with a flat backoff, independent of `generate()`'s own `max_retries` config-driven loop; a page failing twice is recorded as a failed page, not aborting the whole document (confirmed: `failed_pages` list, document still returns success if at least one page succeeded).
- **JSON truncation salvage** via brace-counting (`_salvage_invoices_from_truncated_json`) — duplicated logic, not shared with `ClaudeClient`'s near-identical implementation (confirmed both files have their own copy — a deliberate "each provider file is self-contained" convention per multiple modules' comments).

**Known Fragility**
- **Scanned pages are rasterized locally (`pdf2image`, `SCANNED_PAGE_DPI = 300`) rather than trusting Azure's own internal PDF-to-image conversion** — this exists specifically because the opaque server-side conversion was found to produce real invoice-number corruption in testing (RULES.md RULE-04). Confirmed by source: `_page_has_text_layer()` gates this decision per-page.
- **One Responses API call per page, never the whole document at once** — deliberate architecture per the module docstring, confirmed necessary because a whole-document call was found to time out or silently narrow scope to one page while still reporting success.

**Change Impact** — Not currently reachable via the default `get_ai_client()` call (no explicit `provider_name` anywhere routes here) — only reachable via an explicit `get_ai_client("azure_gpt5_mini"|"azure_gpt5_nano"|"azure_gpt5_1")` call, which no traced caller makes.

**Callers** — M-031 (conditionally, if ever called with `provider_name` in `{"azure_gpt5_mini", "azure_gpt5_nano", "azure_gpt5_1"}` — no confirmed live caller does this)
**Calls** — none (leaf node; lazily imports `openai`, `pypdf`, `pdf2image`)
**Integration Points Used** — IP-003 (Azure OpenAI)
