"""
page_orientation.py

Makes a scanned PDF upright before it is sent to the AI provider.

Why (2026-10-01): A New Age Auto Glass sends its "Sales By Customer" report
as a scan of a page turned 90 degrees. Read sideways, Claude swapped amounts
between neighbouring rows, misread digits (I054482 -> I054492) and sometimes
dropped a line -- differently on every run: the Nutley statement came out
-$95 then +$55 against its printed $8,318.00, with 9 then 5 lines not tying
to NetSuite. The same page rotated upright extracted exactly ($0.00
difference) on two consecutive runs, with only its genuine combined-bill pair
left unmatched.

upright_copy() checks each page's orientation with Tesseract's orientation
and script detection (OSD) and, only when a page is rotated, writes a
temporary copy with that page's /Rotate set so it displays upright. The pixels
are never re-encoded, only the page rotation flag changes. Pages with a real
text layer are left alone (orientation only matters to the vision read of a
scan), and any failure -- no tesseract binary, no OSD data, an unreadable page,
a low-confidence guess -- leaves the PDF exactly as it was: this step can only
help, never block an extraction.
"""

import os
import re
import tempfile

# Below this OSD orientation confidence the guess is ignored -- a sparse or
# noisy page can produce a spurious rotation, and leaving a correctly
# oriented page alone is always safe.
MIN_ORIENTATION_CONFIDENCE = 2.0
# A page with at least this much extractable text has a real text layer.
TEXT_LAYER_MIN_CHARS = 40
MAX_PAGES_CHECKED = 20


def _osd_rotation(page) -> int:
    """Clockwise degrees (0/90/180/270) this rendered page needs to be
    upright, or 0 when unknown or below MIN_ORIENTATION_CONFIDENCE."""
    import pytesseract
    from PIL import Image
    import pymupdf

    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), colorspace=pymupdf.csGRAY)
    image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    osd = pytesseract.image_to_osd(image, config="--psm 0")
    rotate = re.search(r"Rotate:\s*(\d+)", osd)
    confidence = re.search(r"Orientation confidence:\s*([\d.]+)", osd)
    if not rotate or not confidence or float(confidence.group(1)) < MIN_ORIENTATION_CONFIDENCE:
        return 0
    return int(rotate.group(1)) % 360


def upright_copy(pdf_path: str):
    """Returns (path_to_send, rotations). path_to_send is a temporary upright
    copy when any scanned page needed rotating -- the caller deletes it -- or
    pdf_path itself otherwise. rotations maps 1-based page number to the
    clockwise degrees applied."""
    try:
        import pymupdf
        doc = pymupdf.open(pdf_path)
    except Exception as e:
        print(f"  [Orientation] skipped (cannot open PDF: {type(e).__name__})")
        return pdf_path, {}

    rotations = {}
    try:
        for index, page in enumerate(doc):
            if index >= MAX_PAGES_CHECKED:
                break
            if len(page.get_text().strip()) >= TEXT_LAYER_MIN_CHARS:
                continue
            try:
                needed = _osd_rotation(page)
            except Exception as e:
                print(f"  [Orientation] page {index + 1}: detection unavailable ({type(e).__name__}) -- left as is")
                continue
            if needed:
                page.set_rotation((page.rotation + needed) % 360)
                rotations[index + 1] = needed

        if not rotations:
            return pdf_path, {}

        fd, out_path = tempfile.mkstemp(suffix="_upright.pdf")
        os.close(fd)
        doc.save(out_path, garbage=3, deflate=True)
        print(f"  [Orientation] rotated page(s) upright before extraction: {rotations}")
        return out_path, rotations
    except Exception as e:
        print(f"  [Orientation] skipped ({type(e).__name__}: {e})")
        return pdf_path, {}
    finally:
        doc.close()
