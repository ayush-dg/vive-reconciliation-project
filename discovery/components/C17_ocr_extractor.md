## C17 — OCR Extractor
ID: M-032
Layer: pipeline
Source file: `src/ai/ocr_extractor.py`

**Module** — OCR Extractor
**ID** — M-032
**Layer** — pipeline
**Primary Responsibility** — pytesseract-based OCR text extraction for scanned PDF pages, used only by M-031 when a page has no usable text layer.

**Inputs** — `pdf_path`, `page_num`, `dpi` (default 200).

**Outputs** — Raw OCR text for one page (`ocr_page()`) or a whole document (`extract_text_with_ocr()`, not called by any other module this session — appears to be a standalone/legacy whole-document path, superseded by M-031's per-page `ocr_page()` calls).

**Public Interface** — `is_ocr_available() -> bool`, `ocr_page(pdf_path, page_num, dpi=200) -> str`, `extract_text_with_ocr(pdf_path, dpi=200) -> (text, page_count)`.

**Error Behaviour** — `is_ocr_available()` catches any exception (missing package, missing Tesseract binary) and returns `False` rather than raising — the standard way M-031 checks availability before attempting OCR. `extract_text_with_ocr()` raises `RuntimeError` with install instructions if the packages aren't importable at all — the one function in this module that can raise.

**Known Fragility** — `_configure_tesseract_path()` hardcodes a Windows-specific default install path (`C:\Program Files\Tesseract-OCR\tesseract.exe`) as a fallback when `tesseract` isn't already on `PATH` — a non-Windows deployment or a non-default Windows install location silently falls through to whatever `pytesseract`'s own default resolution finds (likely nothing), with `is_ocr_available()` then correctly reporting unavailable, but for a reason (wrong hardcoded path assumption) a deployer might not diagnose quickly.

**Change Impact** — Isolated to the scanned-page fallback path; a regression here degrades (not crashes) M-031's OCR path, since `is_ocr_available()` returning `False` is a handled, expected case throughout M-031.

**Callers** — M-031 (`is_ocr_available`, `ocr_page`)
**Calls** — none
**Integration Points Used** — IP-007 (Tesseract OCR + Poppler, local binaries)
