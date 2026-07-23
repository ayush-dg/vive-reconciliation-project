## C10 — Claude Sonnet 4.6 client
ID: M-023
Layer: pipeline
Source file: src/ai/claude_sonnet_client.py

**Module** — Claude Sonnet 4.6 client
**ID** — M-023
**Layer** — pipeline
**Primary Responsibility** — `AIClient` implementation for Claude Sonnet 4.6 via Azure Foundry (streaming). **Confirmed the actual active extraction primary** — `active_provider.json`'s `provider_chain[0]`, resolved by `client_factory.get_ai_client()` with no argument.

**Inputs** — `ClaudeSonnetClient(config, transport=None)`; `generate(prompt, ...)`; `generate_with_file(pdf_path, prompt)` — **`prompt` parameter is accepted but ignored**; always sends its own embedded `EXTRACTION_PROMPT`.

**Outputs** — `AIResponse` with `parsed_json` built by this client's own `_build_schema()` — every row's `line_confidence` is `ROW_CONFIDENCE` (a hardcoded `0.75` constant), never elicited from the model (no confidence field is even requested in `EXTRACTION_PROMPT`).

**Public Interface**
- `generate(...) -> AIResponse`, `generate_with_file(pdf_path, prompt) -> AIResponse`
- Private: `_build_client()`, `_real_text_call()`, `_real_file_call()` (streaming — `client.messages.stream()` + `get_final_message()`, required because a single whole-document call can run long enough to risk a non-streaming read timeout), `_detect_truncation()`, `_pdfplumber_row_count()`, `_rows_to_invoices()`, `_map_columns()`, `_pick_cleanest_column()`, `_row_to_invoice()`, `_looks_like_invoice_number()`, `_fallback_invoice_number()`, `_fallback_amount()`, `_to_float()`, `_build_schema()`, `_try_parse_json()`, `_salvage_rows_from_truncated_json()`, `_clean_error()`

**Error Behaviour** — Never raises out of `generate_with_file()`/`generate()` — every failure path converts to a clean `AIResponse(success=False)`. Truncation is explicitly *detected* (not just salvaged) via `_detect_truncation()` and treated as an immediate fallback signal, not retried — confirmed: a systematically truncated response would very likely truncate again on retry, so `generate_with_file()` returns failed immediately rather than looping.

**Known Fragility — the central finding of this session's confidence-fabrication investigation**
- **`ROW_CONFIDENCE = 0.75` is hardcoded and applied to every row regardless of actual legibility** (line 521: `"line_confidence": ROW_CONFIDENCE`) — `EXTRACTION_PROMPT` never asks the model for confidence at all. Since `0.75` always clears the `0.60` validation threshold, every row this client extracts always passes into Bronze/Silver, defeating RULE-10's "never silently succeed" design for this provider. Confirmed with live data: 100% of 1,510 (local) + additional (Azure SQL) Bronze rows tagged `claude_sonnet/claude-sonnet-4-6` show exactly `0.75`, zero variance.
- **No totals-row exclusion** — neither the prompt nor `_row_to_invoice()`/`_rows_to_invoices()` filter out a summary/total row; unlike `pdfplumber_fallback.py`'s explicit keyword skip.
- **Column mapping via `_map_columns()`'s keyword lists**, with a value-based fallback for `invoice_number`/`outstanding_amount` only (`_fallback_invoice_number`, `_fallback_amount`) — narrower than `VISION_PROMPT`'s instruction to semantically reason about any unfamiliar column for every field.
- **Its own docstring is stale**, claiming to be "NOT part of the active provider chain (gemini remains primary)" — directly contradicted by `active_provider.json`.

**Change Impact** — This is the highest-consequence module in the whole system for extraction quality — any change here directly affects what confidence signal (or lack thereof) every currently-live vendor-statement invoice carries.

**Callers** — M-031 (conditionally, `provider_name == "claude_sonnet"` — **the default branch given the current `provider_chain`**)
**Calls** — M-028 (`extract_with_pdfplumber`, via `_pdfplumber_row_count()`, used only to judge whether a salvaged truncated response looks suspiciously short)
**Integration Points Used** — IP-001 (Claude Sonnet 4.6)
