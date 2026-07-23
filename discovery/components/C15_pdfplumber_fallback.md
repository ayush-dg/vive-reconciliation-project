## C15 — pdfplumber fallback
ID: M-028
Layer: pipeline
Source file: src/ai/pdfplumber_fallback.py

**Module** — pdfplumber fallback
**ID** — M-028
**Layer** — pipeline
**Primary Responsibility** — Last-resort, deterministic (no-AI) extraction when all AI providers fail; handles both text-based PDFs (geometry-based table extraction) and scanned pages (per-page OCR only where pdfplumber itself finds nothing).

**Inputs** — `extract_with_pdfplumber(pdf_path: str) -> dict`.

**Outputs** — A Universal Financial Document Schema dict, tagged `_extraction_method: "pdfplumber_fallback"` and `_ocr_pages_used` (list of page numbers that needed OCR).

**Public Interface**
- `extract_with_pdfplumber(pdf_path) -> dict`
- Shared helpers, imported directly by `document_intelligence_client.py` (M-024): `_extract_header_info(text)`, `_find_header_row(table)`, `_map_columns(header_row)`, `_extract_invoice_row(row, col_map, page_num, row_num, default_shop, confidence=0.65)`
- Private/internal only: `_try_ocr_page()`, `_ocr_text_to_pseudo_table()`, `_parse_amount()`, `_failed_schema()`

**Error Behaviour** — `extract_with_pdfplumber()` wraps its entire body in `try/except Exception` and returns `_failed_schema()` (a valid-but-empty schema dict with `document_type: "UNKNOWN"`, `warnings` populated) rather than raising — confirmed this is the module's core design guarantee: it "never" propagates an exception to `document_understanding_engine.py`, which relies on that. `is_ocr_available()`/`ocr_page()` calls are further guarded by their own `try/except`, disabling OCR gracefully rather than failing the whole extraction if Tesseract is unreachable.

**Known Fragility**
- **This is the ONE extraction path with a real, differentiated confidence signal** (0.65 real-geometry rows vs. 0.50 OCR-derived rows, the latter deliberately below the 0.60 threshold per RULE-10) — confirmed by this session's cross-provider audit as the exception to the fabricated-confidence pattern found in 4 of 6 registered AI clients.
- **`_extract_invoice_row()` has an explicit totals/header-row skip** (`if invoice_number and any(kw in invoice_number.lower() for kw in ["total", "balance", "subtotal"]): return None`) — the one client-side module with this protection, confirmed absent in `claude_sonnet_client.py`/`gemini_client.py`/`mistral_client.py` during this session's follow-up audit.
- **`_find_header_row()` is a broad keyword-substring scan across ALL rows of a table, not just the top** — safe for pdfplumber's own per-page tables (confirmed: the real header always precedes any footer on the same page), but `document_intelligence_client.py`'s own comment explains this exact function, when applied naively to a *headerless continuation* table, previously misread a trailing "Total Outstanding Invoices..." row as a header — the fix for that (`HEADER_MAX_DATA_START`) lives in M-024, not here, since this function's own use case never had that failure mode.
- **OCR trigger threshold** (`OCR_TRIGGER_TEXT_THRESHOLD = 500`) decides per-page whether a sparse text layer means "scanned, worth OCR'ing" vs. "genuinely non-tabular layout, OCR wouldn't help" — a single hardcoded constant governing a real judgment call, not empirically tuned per the code (no comment claims it was benchmarked).

**Change Impact** — Its column-mapping/header-detection/row-extraction helpers are directly imported (not duplicated) by M-024 — any change here changes that client's behavior too, and the `HEADER_MAX_DATA_START` guard would need re-evaluating if this function's scan logic ever changed.

**Callers** — M-020 (`document_understanding_engine.py`, `extract_with_pdfplumber`), M-024 (`document_intelligence_client.py`, four helper functions imported directly), M-023, M-025 (`claude_sonnet_client.py`, `gemini_client.py`, via `_pdfplumber_row_count()` truncation cross-check)
**Calls** — M-027 (`is_ocr_available`, `ocr_page`)
**Integration Points Used** — IP-007 (Tesseract OCR + Poppler, indirectly via M-027)
