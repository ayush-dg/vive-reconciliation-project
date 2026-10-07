"""
ocr_text.py

OCR text for a scanned PDF (no usable text layer), used ONLY by the
Arithmetic Validation Gate's text-based checks (2026-10-07): the printed
previous balance on a labelled balance-forward line (previous_balance.py)
and the printed total when the extraction returned none (printed_total.py).
It never supplies rows -- the extracted rows are checked against what the
OCR text prints, with the same exact-match rules as a real text layer.

Pages are rendered with PyMuPDF at 300 dpi and read with Tesseract
("--psm 6", one uniform block per page -- the same mode
src/ai/ocr_extractor.py uses). Tesseract is installed in the Docker image
(Dockerfile: tesseract-ocr). Never raises: if OCR is unavailable or fails,
the text is "" and the gate behaves exactly as it did without it.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

OCR_DPI = 300
OCR_CONFIG = "--psm 6"


def ocr_pdf_text(pdf_path: Optional[str]) -> str:
    """Every page's OCR text, joined by newlines; "" when unavailable."""
    if not pdf_path:
        return ""
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
        from src.ai.ocr_extractor import _configure_tesseract_path

        _configure_tesseract_path(pytesseract)
        pages = []
        with fitz.open(pdf_path) as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=OCR_DPI)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                pages.append(pytesseract.image_to_string(image, config=OCR_CONFIG))
        return "\n".join(pages)
    except Exception as e:  # OCR is an optional aid -- never fail the intake over it
        logger.warning("OCR of %s for validation failed (%s: %s)", pdf_path, type(e).__name__, e)
        return ""
