## C12 — Gemini client
ID: M-025
Layer: pipeline
Source file: src/ai/gemini_client.py

**Module** — Gemini client
**ID** — M-025
**Layer** — pipeline
**Primary Responsibility** — `AIClient` implementation for Gemini 2.5 Flash via the google-genai SDK (Files API + `generate_content`, whole document in one call). Registered, apparently a **prior** active primary per its own docstring and `client_factory.py`'s comments — not currently in the active chain.

**Inputs** — `GeminiClient(config, transport=None)`; `generate_with_file(pdf_path, prompt)` — `prompt` accepted but unused; always sends its own `EXTRACTION_PROMPT`.

**Outputs** — `AIResponse` with `parsed_json` built by `_build_schema()`; every row's `line_confidence` is `ROW_CONFIDENCE = 0.75`, hardcoded — same fabrication pattern as M-023.

**Public Interface**
- `generate(...) -> AIResponse`, `generate_with_file(pdf_path, prompt) -> AIResponse`
- Private: `_missing_config_error()`, `_real_text_call()`, `_is_retryable_503()`, `_detect_truncation()`, `_pdfplumber_row_count()`, `_cleanup_file()`, `_rows_to_invoices()`, `_normalize_header()`, `_match_any()`, `_map_columns()`, `_pick_cleanest_column()`, `_row_to_invoice()`, `_looks_like_invoice_number()`, `_fallback_invoice_number()`, `_fallback_amount()`, `_to_float()`, `_build_schema()`, `_try_parse_json()`, `_salvage_rows_from_truncated_json()`, `_clean_error()`

**Error Behaviour**
- **503 UNAVAILABLE gets a dedicated retry path** (`_is_retryable_503()`) — up to `max_503_retries` (default 2) with a 60s wait — distinct from a genuine extraction failure, which fails immediately with no retry.
- **Uploaded files are always cleaned up** (`_cleanup_file()`, best-effort, never lets cleanup failure affect the extraction result) — confirmed called on both the success and every exception path.
- **Truncation detection is two-signal** (`_detect_truncation()`): empty `rows` with non-empty `columns_found`, or a salvaged response with suspiciously few rows relative to `pdfplumber`'s own count on the same document (`_pdfplumber_row_count()`) — the same cross-check pattern M-023 also uses, confirmed independently implemented in both files.

**Known Fragility**
- **Same `ROW_CONFIDENCE = 0.75` fabrication and no-totals-exclusion gap as M-023** — confirmed by this session's cross-provider audit: `_rows_to_invoices()` converts every dict-shaped row unconditionally (only skip condition is `if not isinstance(row, dict): continue`), no keyword-based total/balance/subtotal filter anywhere.
- **Its own module docstring claims to be "the active primary provider in active_provider.json"** — directly false as of this session (`claude_sonnet` is `provider_chain[0]`) — one of the stale AI-provider-chain locations.
- **`_pick_cleanest_column()`'s content-based invoice-number disambiguation** exists because a real vendor (`Fred_Beans_MidNJ_053126.pdf`) prints both a route/account-code-prefixed reference and a clean invoice number in separate columns — confirmed a genuine, previously-encountered ambiguity, not a hypothetical edge case.

**Change Impact** — Shares its column-mapping/fallback logic in spirit (not by import) with M-023 and M-026 — each file is independently self-contained per a deliberate "no shared utils module" convention (confirmed by cross-referencing all three files' near-identical logic and comments acknowledging the pattern).

**Callers** — M-031 (conditionally, `provider_name == "gemini"` — no confirmed live caller does this)
**Calls** — M-028 (`extract_with_pdfplumber`, via `_pdfplumber_row_count()`, truncation-detection cross-check only)
**Integration Points Used** — IP-005 (Google Gemini)
