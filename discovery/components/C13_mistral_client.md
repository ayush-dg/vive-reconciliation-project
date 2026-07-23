## C13 — Mistral client
ID: M-026
Layer: pipeline
Source file: src/ai/mistral_client.py

**Module** — Mistral client
**ID** — M-026
**Layer** — pipeline
**Primary Responsibility** — `AIClient` implementation for Mistral Medium via the direct Mistral API (OpenAI-compatible chat completions). Registered, never confirmed as an active primary at any point — available for a deliberate provider swap.

**Inputs** — `MistralClient(config, transport=None)`; `generate_with_file(pdf_path, prompt)` — `prompt` accepted but unused; always sends its own `EXTRACTION_PROMPT`.

**Outputs** — `AIResponse` with `parsed_json` built by `_build_schema()`. Every row's `line_confidence` is `ROW_CONFIDENCE = 0.75`, hardcoded.

**Public Interface**
- `generate(...) -> AIResponse`, `generate_with_file(pdf_path, prompt) -> AIResponse`
- Private: `_missing_config_error()`, `_real_text_call()`, `_process_single_page()`, `_real_page_call()`, `_row_to_invoice()`, `_to_float()`, `_build_schema()`, `_try_parse_json()`, `_salvage_rows_from_truncated_json()`, `_clean_error()`

**Error Behaviour** — Per-page retry-once (fresh call, no backoff/multiplier — distinct from `generate()`'s own outer retry loop), matching M-021's per-page pattern. A page failing twice is recorded as a failed page; the whole document only fails if *every* page failed.

**Known Fragility**
- **Cannot send PDFs natively** — confirmed via diagnostic testing (per the module docstring) that Mistral's chat-completions `image_url` content part rejects `application/pdf` data URIs outright ("Unsupported image url scheme"). Every page is rasterized to PNG via `pdf2image` first, one chat-completions call per page.
- **Deliberately does not ask for per-row confidence or document/vendor/statement metadata at all** — the module docstring explains this was a deliberate choice after diagnostic testing found the model's self-reported confidence and row counts were unreliable (100% "HIGH" confidence regardless of known transcription errors; the model's own row count disagreeing with its own output on 12 of 14 test pages). So `ROW_CONFIDENCE = 0.75` here is a considered fallback to a fixed placeholder given a demonstrated-unreliable signal — a different rationale from M-023/M-025's cases, though the downstream effect (defeats the 0.60 threshold) is identical.
- **Stashes the raw per-column dict into the schema's `description` field as JSON** — explicitly marked TEMPORARY in the code comment, purely so the full per-vendor column set is inspectable in Bronze/Silver after a real run, not because `description` is the right long-term home for it.
- **No totals-row exclusion**, same gap as M-023/M-025.

**Change Impact** — Registered but effectively unused in any traced live path — a provider swap to Mistral would need `active_provider.json`'s `provider_chain` updated; no other code change required given the `AIClient` abstraction.

**Callers** — M-031 (conditionally, `provider_name == "mistral"` — no confirmed live caller does this)
**Calls** — none directly (leaf node; lazily imports `openai` (OpenAI-compatible client pointed at Mistral's endpoint), `pdf2image`)
**Integration Points Used** — IP-006 (Mistral)
