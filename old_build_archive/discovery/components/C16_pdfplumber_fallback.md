## C16 — pdfplumber Fallback Extraction
ID: M-031
Layer: pipeline
Source file: `src/ai/pdfplumber_fallback.py`

**Module** — pdfplumber Fallback Extraction
**ID** — M-031
**Layer** — pipeline
**Primary Responsibility** — Last-resort, deterministic (no AI, no cost, works offline) extraction — geometry-based table extraction for text PDFs, with per-page OCR (via M-032) for pages where pdfplumber finds no usable text layer.

**Inputs** — `pdf_path`.

**Outputs** — A Universal Financial Document Schema dict (not an `AIResponse` — this module predates/sits outside the `AIClient` contract, called directly by function, not via M-023).

**Public Interface** — `extract_with_pdfplumber(pdf_path) -> dict` (primary entry point); `_extract_header_info`, `_find_header_row`, `_map_columns`, `_extract_invoice_row` (also imported directly by M-028 as shared helpers, despite the leading underscore suggesting module-private).

**Error Behaviour** — Never raises — any exception during extraction is caught at the top level and converted to `_failed_schema()` (zero invoices, `UNKNOWN` document type, the exception message recorded as a warning).

**Known Fragility**
- **The underscore-prefixed helper functions (`_extract_header_info`, `_find_header_row`, `_map_columns`, `_extract_invoice_row`) are imported directly by M-028** — Python's leading-underscore convention signals "module-private" but these four are a real, load-bearing cross-module contract. A refactor treating them as safe to rename/change because they "look private" would silently break M-028.
- `_ocr_text_to_pseudo_table()`'s column-splitting logic (2+-space runs, falling back to any-whitespace-run splitting only when a line collapses to one cell) was fixed `6aadbf1` (2026-08-05) after producing 0 usable invoices on a real scanned sample — confirmed this session as the current, corrected behavior. The fallback is deliberately scoped to the single-cell-collapse case specifically so a real multi-word value a 2+-space split correctly keeps together isn't shredded.
- `_map_columns()`'s keyword-based mapping (RULE-07) is the same generic pattern every provider client duplicates independently — a genuinely new vendor column-naming convention that this function's keyword lists don't recognize silently produces an unmapped field (null), not an error.

**Change Impact** — Called by M-024 (as the deterministic fallback for every provider failure), M-025 and M-029 (for truncation-detection row counts), and M-028 (for its shared column-mapping helpers) — a change to any of the four shared helper functions has a four-module blast radius, not just this file's own primary entry point.

**Callers** — M-024, M-025, M-028, M-029
**Calls** — M-032 (`is_ocr_available`, `ocr_page`)
**Integration Points Used** — IP-007 (Tesseract/Poppler, transitively via M-032)
