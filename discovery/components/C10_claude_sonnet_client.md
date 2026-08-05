## C10 — Claude Sonnet 4.6 Client
ID: M-025
Layer: pipeline
Source file: `src/ai/claude_sonnet_client.py`

**Module** — Claude Sonnet 4.6 Client
**ID** — M-025
**Layer** — pipeline
**Primary Responsibility** — Active primary extraction provider. Sends the whole PDF as one base64 document block via a streaming Anthropic Messages API call (Azure Foundry), maps the response into invoice rows.

**Inputs** — `config` (`config/ai/claude_sonnet_extraction.json`), `pdf_path`; env vars `AZURE_CLAUDE_API_KEY`/`AZURE_CLAUDE_ENDPOINT`/`AZURE_CLAUDE_SONNET_DEPLOYMENT`.

**Outputs** — `AIResponse` wrapping a Universal Financial Document Schema dict (via `generate_with_file()`), or a plain-text response (via `generate()`, not exercised by the extraction pipeline).

**Public Interface** — `ClaudeSonnetClient(config, transport=None)`, `.generate()`, `.generate_with_file(pdf_path, prompt)` — `prompt` accepted for `AIClient` interface parity but unused; this client always sends its own internal `EXTRACTION_PROMPT`.

**Error Behaviour** — Never raises out of either public method — every failure path (missing config, API error, JSON parse failure, detected truncation) returns a clean `AIResponse(success=False, ...)`. Retries `max_retries` times (config-driven, default 2) with exponential backoff for `generate()`; `generate_with_file()` retries the same way but treats a *detected truncation* as non-retryable (returns failed immediately, since retrying the same model on the same document would very likely truncate again).

**Known Fragility**
- `ROW_CONFIDENCE = 0.75` feeds only the document-level `extraction_confidence.overall` field when the transport-injected test path is used, or as a fallback constant in `_build_schema()` — genuine **per-row** confidence comes from `_parse_confidence()` reading the model's own `"confidence"` field per row, falling back to `FALLBACK_LINE_CONFIDENCE = 0.40` only when that field is missing/unparseable/out-of-range. A reader conflating `ROW_CONFIDENCE` with per-row confidence would misdiagnose this client's actual confidence-scoring behavior.
- `_detect_truncation()`'s second signal (salvaged row count `< 10%` of pdfplumber's row count) calls M-031's `extract_with_pdfplumber()` synchronously mid-request purely to get a comparison count — a real, uncounted extra cost (a full deterministic extraction pass) on every truncated-response case, not just on genuine fallback.
- `ai_call_slot()` (M-041) wraps only the real network call inside `_real_file_call()`/`_real_text_call()` — a test-injected `_transport` bypasses the concurrency limiter entirely, which is correct for offline tests but means the limiter's behavior itself is never exercised by this client's own test suite (if one exists — not verified this session).

**Change Impact** — As the active primary, any regression here directly affects the extraction quality/availability of every live statement processed — the fallback (M-031) is deterministic and lower-fidelity, so a broken M-025 degrades but does not halt the pipeline.

**Callers** — M-023 (`get_ai_client("claude_sonnet")`, instantiation)
**Calls** — M-041 (`ai_call_slot()`), M-031 (`extract_with_pdfplumber`, for truncation-detection row count only)
**Integration Points Used** — IP-001 (Claude Sonnet 4.6, Azure AI Foundry)
