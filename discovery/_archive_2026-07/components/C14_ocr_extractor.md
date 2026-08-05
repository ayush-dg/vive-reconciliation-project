## C14 — OCR extractor
ID: M-027
Layer: pipeline
Source file: src/ai/ocr_extractor.py

**Module** — OCR extractor
**ID** — M-027
**Layer** — pipeline
**Primary Responsibility** — Extracts text from scanned PDF pages using pytesseract; last resort when pdfplumber finds no text layer or the primary AI provider is unavailable.

**Inputs** — `is_ocr_available() -> bool`; `ocr_page(pdf_path, page_num, dpi=200) -> str`; `extract_text_with_ocr(pdf_path, dpi=200) -> (str, int)`.

**Outputs** — Raw OCR text per page (or the whole document via `extract_text_with_ocr`).

**Public Interface**
- `is_ocr_available() -> bool`
- `ocr_page(pdf_path, page_num, dpi=200) -> str` — single-page only, called by `pdfplumber_fallback.py`.
- `extract_text_with_ocr(pdf_path, dpi=200) -> (str, int)` — whole-document, same return shape as `document_understanding_engine.extract_pdf_text()`.
- `_configure_tesseract_path(pytesseract)` (private) — Windows-specific binary path resolution.

**Error Behaviour** — `is_ocr_available()` wraps its whole check (import + `get_tesseract_version()`) in a `try/except Exception: return False` — any missing dependency (pytesseract, pdf2image) or unreachable Tesseract binary degrades to "OCR unavailable" cleanly, never raising into the caller. `extract_text_with_ocr()` (the whole-document function) raises a clear `RuntimeError` with install instructions if dependencies are missing — the one function in this module that does NOT silently degrade, since it's meant to be a deliberate, direct call, not a background fallback check.

**Known Fragility** — `_configure_tesseract_path()` hardcodes a Windows-specific default install path (`C:\Program Files\Tesseract-OCR\tesseract.exe`) as a fallback when `tesseract` isn't on `PATH` — this module has no equivalent fallback path resolution for Linux/macOS, meaning on a non-Windows deployment (e.g. the Azure App Service Linux production target), OCR availability depends entirely on `tesseract` being on `PATH` with no hardcoded fallback to try.

**Change Impact** — `ocr_page()`'s single-page interface is what `pdfplumber_fallback.py` actually depends on operationally (per-page, on-demand OCR only for pages pdfplumber itself found nothing on) — `extract_text_with_ocr()` (whole-document) has no confirmed caller in the traced call graph; it appears to be an alternate/legacy entry point.

**Callers** — M-028 (`is_ocr_available`, `ocr_page`)
**Calls** — none (leaf node; lazily imports `pytesseract`, `pdf2image`)
**Integration Points Used** — IP-007 (Tesseract OCR + Poppler, local binaries)
