"""
ocr_extractor.py

Extracts text from scanned PDF pages using pytesseract OCR.
Used as a last resort when:
  1. pdfplumber finds no text (scanned PDF)
  2. Gemini vision is unavailable (quota exceeded)

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


def _configure_tesseract_path(pytesseract) -> None:
    """Point pytesseract at the Tesseract binary on Windows.

    pytesseract defaults to just "tesseract", which fails if the install
    directory isn't on PATH at the time Python starts.
    """
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


def extract_text_with_ocr(pdf_path: str, dpi: int = 200):
    """
    Convert each PDF page to an image and run OCR on it.
    Returns (text, page_count) — same shape as extract_pdf_text().

    dpi=200 is a good balance between speed and accuracy for
    typical vendor statement PDFs. Increase to 300 for small text.
    """
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError as e:
        raise RuntimeError(
            f"OCR dependencies not installed: {e}\n"
            f"Run: pip install pytesseract pdf2image\n"
            f"And install Tesseract: https://github.com/UB-Mannheim/tesseract/wiki"
        )
    _configure_tesseract_path(pytesseract)

    print(f"  [OCR] Converting PDF pages to images (dpi={dpi})...")
    images = convert_from_path(pdf_path, dpi=dpi)
    page_count = len(images)
    pages_text = []

    for i, image in enumerate(images, start=1):
        print(f"  [OCR] Running OCR on page {i}/{page_count}...")
        text = pytesseract.image_to_string(image, config="--psm 6")
        pages_text.append(f"--- PAGE {i} ---\n{text}")

    full_text = "\n\n".join(pages_text)
    print(f"  [OCR] Extracted {len(full_text)} characters from {page_count} pages")
    return full_text, page_count
