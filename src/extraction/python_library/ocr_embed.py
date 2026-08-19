"""
Reusable OCR text-embedding step for scanned (image-only) PDFs.

Design: pdfplumber can only read text that is actually embedded in the PDF.
For a scanned PDF (page image, zero extractable text), this module OCRs each
page's image and writes the recognized words back into the PDF as an
invisible text layer (PDF text render mode 3), positioned to match the
original words. The visible page still shows the original scan image
unchanged; pdfplumber (or any text-based tool) can now "see" the text
underneath it, just like a normal digitally-created PDF.

This mirrors what tools like ocrmypdf do, built directly on
pytesseract + PyMuPDF so the whole pipeline stays in this project's
existing pdfplumber-based extraction pattern.

Accuracy caveat: OCR on a scanned image is NOT as reliable as a PDF's
native embedded text. Long numeric IDs and similar-looking digits
(6/8, 1/4, 2/7) are the most error-prone. Always spot-check extracted
numeric fields (invoice numbers, amounts) against the original scan.
"""

import io

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
OCR_UPSCALE = 3.0  # empirically best balance of accuracy vs speed for ~200dpi scans
OCR_PSM = 6
MIN_CONFIDENCE = 30  # skip garbage low-confidence tokens (noise, stray marks)

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def has_embedded_text(pdf_path, min_chars_per_page=20):
    """Quick check: does this PDF already have real embedded text?"""
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if len(text.strip()) >= min_chars_per_page:
                return True
    return False


def _page_to_pil_image(page, zoom=2.0):
    """Render a PDF page to a PIL image at a given zoom factor (relative to 72dpi)."""
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    return Image.open(io.BytesIO(pix.tobytes("png")))


def make_searchable(input_pdf_path, output_pdf_path, render_zoom=2.0):
    """
    OCR every page of input_pdf_path and write output_pdf_path: same visible
    page images, plus an invisible text layer aligned to each recognized word.
    Returns the number of words embedded (for sanity-checking the run).
    """
    src = fitz.open(input_pdf_path)
    out = fitz.open()
    total_words = 0

    for page in src:
        page_img = _page_to_pil_image(page, zoom=render_zoom)

        ocr_img = page_img.convert("L")
        w, h = ocr_img.size
        ocr_img = ocr_img.resize((int(w * OCR_UPSCALE), int(h * OCR_UPSCALE)), Image.LANCZOS)

        data = pytesseract.image_to_data(
            ocr_img, config=f"--psm {OCR_PSM}", output_type=pytesseract.Output.DICT
        )

        new_page = out.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=_pil_to_png_bytes(page_img))

        # Map OCR-image pixel coords back to PDF point coords (page.rect space).
        sx = page.rect.width / ocr_img.width
        sy = page.rect.height / ocr_img.height

        n = len(data["text"])
        for i in range(n):
            word = data["text"][i].strip()
            conf = int(float(data["conf"][i])) if data["conf"][i] not in ("-1", "") else -1
            if not word or conf < MIN_CONFIDENCE:
                continue
            x0 = data["left"][i] * sx
            y0 = data["top"][i] * sy
            height = data["height"][i] * sy
            width = data["width"][i] * sx
            fontsize = max(height * 0.85, 1.0)
            try:
                new_page.insert_text(
                    (x0, y0 + height * 0.85),
                    word,
                    fontsize=fontsize,
                    render_mode=3,  # invisible
                    fontname="helv",
                )
                total_words += 1
            except Exception:
                continue

    out.save(output_pdf_path)
    out.close()
    src.close()
    return total_words


def _pil_to_png_bytes(pil_img):
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    return buf.getvalue()


def ensure_searchable(input_pdf_path, output_pdf_path):
    """If input already has real text, return it unchanged; else OCR it."""
    if has_embedded_text(input_pdf_path):
        return input_pdf_path
    make_searchable(input_pdf_path, output_pdf_path)
    return output_pdf_path


if __name__ == "__main__":
    import sys

    inp = sys.argv[1]
    outp = sys.argv[2] if len(sys.argv) > 2 else inp.replace(".pdf", " - OCR.pdf")
    n = make_searchable(inp, outp)
    print(f"Embedded {n} words into {outp}")
