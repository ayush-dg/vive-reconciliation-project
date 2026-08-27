## C14 — Gemini Client
ID: M-029
Layer: pipeline
Source file: `src/ai/gemini_client.py`

**Module** — Gemini Client
**ID** — M-029
**Layer** — pipeline
**Primary Responsibility** — Dormant (not in the active chain). Uploads the whole PDF once via the Files API and sends one `generate_content` call; validated in diagnostic testing as reliable across all 4 sample vendor statements.

**Inputs** — `config` (`config/ai/gemini.json`); env var `GEMINI_API_KEY`.

**Outputs** — `AIResponse` wrapping a Universal Financial Document Schema dict.

**Public Interface** — `GeminiClient(config, transport=None)`, `.generate()`, `.generate_with_file()`.

**Error Behaviour** — Never raises. Specifically retries on a 503 UNAVAILABLE response (up to `max_retries`, 60s wait) — any other error (bad JSON, auth, 4xx) fails immediately with no retry, falling through to the next provider in the chain. Detects truncation via the same two-signal approach as M-025 (empty rows with non-empty columns_found; or a salvaged row count under 10% of pdfplumber's count).

**Known Fragility** — `_cleanup_file()` (deletes the uploaded file from Gemini's Files API after use) is called on every exit path including exceptions, but is itself wrapped in a bare `except Exception: pass` — a cleanup failure is invisible; uploaded files could accumulate on Gemini's side with no local signal.

**Change Impact** — None currently — dormant. Column-agnostic mapping logic here is duplicated (not shared) with M-025's near-identical implementation, per the module's own docstring precedent ("self-contained here, same precedent as MistralClient/GeminiClient not sharing a utils module") — any bug fix to one's mapping logic (e.g. the currency-shape fallback guard) does not automatically apply to the other.

**Callers** — M-023 (`get_ai_client("gemini")`, instantiation — no current caller reaches this without an explicit provider name)
**Calls** — M-031 (`extract_with_pdfplumber`, for truncation-detection row count only)
**Integration Points Used** — IP-005 (Google Gemini 2.5 Flash)
