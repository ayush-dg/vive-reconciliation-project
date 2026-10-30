"""
ocr_extractor.py

Extracts text from scanned PDF pages using pytesseract OCR.
Used as a last resort when:
  1. pdfplumber finds no text (scanned PDF)
  2. The primary AI provider (Claude Sonnet 4.6, see RULES.md RULE-04) is unavailable (quota exceeded)
     [Corrected 2026-07-24, BCE Stage 3 documentation sweep — previously named
     Azure OpenAI gpt-5-mini, stale relative to active_provider.json.]

Returns the same (text, page_count) tuple as extract_pdf_text() in
document_understanding_engine.py — so the rest of the pipeline is unchanged.

Dependencies (optional — gracefully skipped if not installed):
  pip install pytesseract pdf2image
  + Tesseract OCR binary: https://github.com/UB-Mannheim/tesseract/wiki
  + Poppler (required by pdf2image): https://github.com/oschwartz10612/poppler-windows
"""

import os
import platform
import shutil


TESSERACT_THREADS_ENV = "VIVE_TESSERACT_THREADS"


def apply_tesseract_thread_limit() -> None:
    """VIVE_TESSERACT_THREADS=<n> caps every Tesseract run of this process
    at n threads (2026-10-25): Tesseract reads OMP_THREAD_LIMIT, and
    pytesseract starts it with this process's environment. Unset, blank or
    not a positive whole number: nothing is changed (Tesseract's own
    default, as before)."""
    raw = (os.environ.get(TESSERACT_THREADS_ENV) or "").strip()
    if raw.isdigit() and int(raw) > 0:
        os.environ["OMP_THREAD_LIMIT"] = str(int(raw))


def _configure_tesseract_path(pytesseract) -> None:
    """Point pytesseract at the Tesseract binary on Windows, and apply
    VIVE_TESSERACT_THREADS (apply_tesseract_thread_limit) on every platform.

    pytesseract defaults to just "tesseract", which fails if the install
    directory isn't on PATH at the time Python starts.
    """
    apply_tesseract_thread_limit()
    if platform.system() != "Windows":
        return
    tess_path = shutil.which("tesseract")
    if not tess_path:
        default_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.exists(default_path):
            tess_path = default_path
    if tess_path:
        pytesseract.pytesseract.tesseract_cmd = tess_path


def is_ocr_available() -> bool:
    """Returns True if pytesseract and pdf2image are both installed and the
    Tesseract binary is actually reachable."""
    try:
        import pytesseract
        import pdf2image
        _configure_tesseract_path(pytesseract)
        # Also check the Tesseract binary is actually present
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_page(pdf_path: str, page_num: int, dpi: int = 200) -> str:
    """
    Run OCR on a single PDF page (1-indexed, matching pdfplumber's own page
    numbering) and return its raw text.

    Only rasterizes the requested page (via pdf2image's first_page/last_page),
    not the whole document. Used by pdfplumber_fallback.py to OCR just the
    specific pages where pdfplumber's own table extraction found nothing,
    instead of paying the OCR cost for every page up front.
    """
    import pytesseract
    from pdf2image import convert_from_path

    _configure_tesseract_path(pytesseract)

    images = convert_from_path(pdf_path, dpi=dpi, first_page=page_num, last_page=page_num)
    if not images:
        return ""
    return pytesseract.image_to_string(images[0], config="--psm 6")

