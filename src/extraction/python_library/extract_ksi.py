"""
Extract KSI (Noakers) statement PDF into:
  1. KSI (Noakers) 053126 - full text.txt   (layout-preserved OCR text, all pages)
  2. KSI (Noakers) 053126 - line items.csv  (structured order/return line items)
  3. KSI (Noakers) 053126 - summary.csv     (header info + aged-balance summary)

This PDF is a SCANNED image (zero embedded text - confirmed via pdfplumber
probe), unlike the Fred Beans statement. Pipeline:
  1. ocr_embed.ensure_searchable() OCRs each page and embeds the recognized
     words as an invisible text layer back into a new PDF, so pdfplumber can
     read it exactly like a native digital PDF.
  2. Line items are reconstructed from extract_words() using x0 column
     boundaries measured directly from this document's OCR'd word positions
     (posting date / document no. / PO no. / description / customer no. /
     due date / amount).

Accuracy caveat: this document is OCR'd, not natively digital - unlike the
Fred Beans / asTech / Empire statements. On the one KSI statement this was
built against, whole-page OCR alone dropped rows and misread digits;
getting a fully accurate result required manually verifying every line
against high-resolution crops of the source scan, which a script can't do
unattended (see finalize_ksi_verified.py for that one-off, hand-verified
result). This function does the same automated pipeline - OCR + per-row
targeted amount refinement - and reports how it reconciles against any
printed total it can find, but on a scanned, handwriting-annotated
statement, that automated result should still be treated as a best effort,
not a guarantee, and spot-checked against the source scan before relying
on it for reconciliation.
"""

import io
import os
import re

import fitz  # PyMuPDF
import pdfplumber
import pytesseract
from PIL import Image

from ocr_embed import ensure_searchable, TESSERACT_CMD

VENDOR_SIGNATURE = ["KSI Trading Corp", "KSI"]

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# Targeted refinement: the whole-page OCR pass is noisy for the money
# column (surrounding text/handwriting confuses tesseract). Re-cropping a
# tight, high-zoom strip of just the amount column for one row at a time -
# rendered fresh from the original scan, not the whole-page OCR pass -
# and re-running tesseract on that alone gives far cleaner digit
# recognition (verified by direct visual comparison against the source
# scan on this document).
AMOUNT_COL_X0 = 508  # narrowed from 495: handwritten annotations left of the
# amount column (circles/checkmarks) were bleeding into wider crops and
# confusing tesseract's segmentation; 508 clears them while still leaving
# margin before the leftmost real amount glyph (measured min x0 ~514.5)
AMOUNT_COL_X1 = 552
REFINE_ZOOM = 8
REFINE_Y_ABOVE = 6
REFINE_Y_BELOW = 9
AMOUNT_FOUND_RE = re.compile(r"-?\d+\.\d{2}")

# Config chosen by grid search (zoom x psm x whitelist) against 11 rows whose
# amounts were confirmed unambiguous by direct visual read of a full-row crop
# (document number and amount visible together). zoom=8/psm=6 scored 10/11 -
# the one miss was a single glyph misread ("1"->"7") consistent across every
# config tried, i.e. a genuinely ambiguous character on the source scan, not
# a config problem.
REFINE_OCR_CONFIG = "--psm 6"


def refine_amount(page, row_top):
    mat = fitz.Matrix(REFINE_ZOOM, REFINE_ZOOM)
    clip = fitz.Rect(AMOUNT_COL_X0, row_top - REFINE_Y_ABOVE, AMOUNT_COL_X1, row_top + REFINE_Y_BELOW)
    pix = page.get_pixmap(matrix=mat, clip=clip)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    text = pytesseract.image_to_string(img, config=REFINE_OCR_CONFIG).replace(",", ".")
    m = AMOUNT_FOUND_RE.search(text)
    return m.group(0) if m else ""


# --- Gap recovery ---------------------------------------------------------
# The whole-page OCR pass sometimes misses a row's words entirely (not from
# handwriting occlusion - checked visually, the rows are legible - just a
# tesseract detection miss on this scan). Missed rows show up as a gap in
# the vertical spacing between consecutive detected rows roughly 2x the
# normal row height. Rather than silently under-reporting, re-crop exactly
# that gap and OCR it directly. Date/doc-number recovery in isolation was
# less reliable than the rest of the row (still occasional single-digit
# ambiguity even after tuning crop window/zoom/psm) - recovered rows are
# flagged via "recovered": True so those specific ~digits get a human
# glance instead of the whole document.
GAP_RATIO_THRESHOLD = 1.6
DATEDOC_X0, DATEDOC_X1 = 0, 160
DATEDOC_ZOOM = 10
DATEDOC_Y_ABOVE, DATEDOC_Y_BELOW = 5, 8
DATEDOC_CONFIG = "--psm 6"
DATE_FIND_RE = re.compile(r"\d{2}/\d{2}/\d{2}")
DOC_NO_FIND_RE = re.compile(r"[A-Za-z0-9]{6,}")


def ocr_column(page, x0, x1, row_top, y_above, y_below, zoom, config):
    mat = fitz.Matrix(zoom, zoom)
    clip = fitz.Rect(x0, row_top - y_above, x1, row_top + y_below)
    pix = page.get_pixmap(matrix=mat, clip=clip)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img, config=config).strip()


def recover_row(page, row_top):
    """Best-effort re-OCR of one row the whole-page pass missed entirely."""
    datedoc_text = ocr_column(page, DATEDOC_X0, DATEDOC_X1, row_top,
                               DATEDOC_Y_ABOVE, DATEDOC_Y_BELOW, DATEDOC_ZOOM, DATEDOC_CONFIG)
    date_m = DATE_FIND_RE.search(datedoc_text)
    posting_date = date_m.group(0) if date_m else ""
    after_date = datedoc_text[date_m.end():] if date_m else datedoc_text
    doc_m = DOC_NO_FIND_RE.search(after_date)
    document_no = doc_m.group(0) if doc_m else ""

    other_cols = {}
    for name, x0, x1 in COLUMN_BOUNDS:
        if name in ("posting_date", "document_no", "amount"):
            continue
        other_cols[name] = ocr_column(page, x0, x1, row_top, 4, 7, 10, "--psm 7").strip()

    po_no = other_cols["po_no"]
    description = other_cols["description"]
    customer_no = other_cols["customer_no"]
    due_date_raw = other_cols["due_date"]

    due_m = DATE_FIND_RE.search(due_date_raw)
    amount = refine_amount(page, row_top)  # the already-tuned amount-column config

    return {
        "posting_date": posting_date,
        "document_no": document_no,
        "po_no": po_no,
        "description": description,
        "customer_no": customer_no,
        "due_date": due_m.group(0) if due_m else "",
        "amount": amount,
    }


def find_gaps_and_recover(page, found_tops):
    """found_tops: sorted list of row 'top' values already detected on this
    page. Returns a list of recovered row dicts for any gap wide enough to
    hold a missed row, each tagged with its estimated row_top."""
    if len(found_tops) < 3:
        return []
    spacings = sorted(b - a for a, b in zip(found_tops, found_tops[1:]))
    median_spacing = spacings[len(spacings) // 2]

    recovered = []
    for a, b in zip(found_tops, found_tops[1:]):
        gap = b - a
        if gap < median_spacing * GAP_RATIO_THRESHOLD:
            continue
        n_missing = round(gap / median_spacing) - 1
        for i in range(1, n_missing + 1):
            est_top = a + (gap * i / (n_missing + 1))
            row = recover_row(page, est_top)
            row["row_top"] = est_top
            recovered.append(row)
    return recovered


ROW_TOLERANCE = 3.0

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
MONEY_RE = re.compile(r"^-?[\d,]+[.,]\d{2}$")
CUSTNO_RE = re.compile(r"^\d{2}-[A-Za-z0-9]+$")

# Column boundaries (x0), measured from this document's OCR'd word positions.
COLUMN_BOUNDS = [
    ("posting_date", 0, 95),
    ("document_no", 95, 150),
    ("po_no", 150, 220),
    ("description", 220, 335),
    ("customer_no", 335, 395),
    ("due_date", 395, 460),
    ("amount", 460, 10_000),
]


def bucket_column(x0):
    for name, lo, hi in COLUMN_BOUNDS:
        if lo <= x0 < hi:
            return name
    return None


def normalize_amount(text):
    """OCR sometimes reads the decimal point as a comma (e.g. '152,00')."""
    if MONEY_RE.match(text) and "," in text and "." not in text:
        text = text[::-1].replace(",", ".", 1)[::-1]
    return text


def group_rows(words):
    """Group words into rows by top position, using a rolling comparison
    against the previous word (not a fixed anchor) - OCR word boxes jitter
    more than native PDF text, so a single visual row's top can drift by
    several points from its first word to its last."""
    rows = []
    last_top = None
    current_row = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if last_top is None or abs(w["top"] - last_top) <= ROW_TOLERANCE:
            current_row.append(w)
        else:
            rows.append(current_row)
            current_row = [w]
        last_top = w["top"]
    if current_row:
        rows.append(current_row)
    return rows


def parse_header_info(page1_text):
    info = {}
    m = re.search(r"As\s*of\s*(\d{2}/\d{2}/\d{2})", page1_text, re.IGNORECASE)
    if m:
        info["statement_as_of"] = m.group(1)
    m = re.search(r"Customer[,:.]?\s*No\.?:?\s*([\d A-Za-z-]+\d)", page1_text)
    if m:
        info["customer_no"] = m.group(1).strip()
    m = re.search(r"(VIVE COLLISION[^\n]*)", page1_text, re.IGNORECASE)
    if m:
        info["customer_name"] = m.group(1).strip()
    m = re.search(r"(\d+ [^\n]*(?:Rd|Road|St|Ave|Blvd)[^\n]*)\n\s*([A-Za-z]+)\s+([A-Z]{2})\s+(\d{5})", page1_text)
    if m:
        info["billing_address"] = m.group(1).strip()
        info["billing_city"] = m.group(2).strip()
        info["billing_state"] = m.group(3).strip()
        info["billing_zip"] = m.group(4).strip()
    return info


def extract(pdf_path, output_dir=None):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": str}.

    As a side effect, writes "<pdf stem> - OCR.pdf" - the searchable version
    with the embedded invisible text layer - into output_dir (default: next
    to the input PDF)."""
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    out_dir = output_dir or os.path.dirname(pdf_path) or "."
    searchable_pdf = os.path.join(out_dir, f"{stem} - OCR.pdf")
    ensure_searchable(pdf_path, searchable_pdf)

    all_text_pages = []
    line_items = []
    header_info = {}
    refined_count = 0

    original_doc = fitz.open(pdf_path)

    with pdfplumber.open(searchable_pdf) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            layout_text = page.extract_text(layout=True) or ""
            all_text_pages.append(f"{'=' * 80}\nPAGE {page_num}\n{'=' * 80}\n{layout_text}")

            if page_num == 1:
                header_info = parse_header_info(page.extract_text() or "")

            words = page.extract_words()
            rows = group_rows(words)
            original_page = original_doc[page_num - 1]

            page_items = []
            found_tops = []
            for row in rows:
                cols = {name: [] for name, _, _ in COLUMN_BOUNDS}
                for w in row:
                    col = bucket_column(w["x0"])
                    if col:
                        cols[col].append(w)

                posting_date = " ".join(w["text"] for w in cols["posting_date"])
                document_no = " ".join(w["text"] for w in cols["document_no"])
                po_no = " ".join(w["text"] for w in cols["po_no"])
                description = " ".join(w["text"] for w in sorted(cols["description"], key=lambda w: w["x0"]))
                customer_no = " ".join(w["text"] for w in cols["customer_no"])
                due_date = " ".join(w["text"] for w in cols["due_date"])
                amount = " ".join(normalize_amount(w["text"]) for w in cols["amount"])

                # A genuine line-item row has a posting date and a document number.
                if DATE_RE.match(posting_date) and document_no:
                    row_tops = sorted(w["top"] for w in row)
                    row_top = row_tops[len(row_tops) // 2]  # median - robust to one noisy word
                    found_tops.append(row_top)
                    refined = refine_amount(original_page, row_top)
                    was_refined = bool(refined)
                    if refined:
                        amount = refined
                        refined_count += 1

                    page_items.append({
                        "page": page_num,
                        "posting_date": posting_date,
                        "document_no": document_no,
                        "po_no": po_no,
                        "description": description,
                        "customer_no": customer_no,
                        "due_date": due_date if DATE_RE.match(due_date) else "",
                        "amount": amount,
                        "amount_refined": was_refined,
                        "recovered": False,
                        "_row_top": row_top,
                    })

            found_tops.sort()
            for recovered in find_gaps_and_recover(original_page, found_tops):
                if recovered["amount"]:
                    refined_count += 1
                page_items.append({
                    "page": page_num,
                    "posting_date": recovered["posting_date"],
                    "document_no": recovered["document_no"],
                    "po_no": recovered["po_no"],
                    "description": recovered["description"],
                    "customer_no": recovered["customer_no"],
                    "due_date": recovered["due_date"],
                    "amount": recovered["amount"],
                    "amount_refined": bool(recovered["amount"]),
                    "recovered": True,
                    "_row_top": recovered["row_top"],
                })

            page_items.sort(key=lambda r: r["_row_top"])
            for item in page_items:
                del item["_row_top"]
            line_items.extend(page_items)

    original_doc.close()

    fieldnames = ["page", "posting_date", "document_no", "po_no", "description",
                  "customer_no", "due_date", "amount", "amount_refined", "recovered"]

    # Best-effort reconciliation: sum the extracted amount column and compare
    # to any printed total this OCR pass could find. Unlike the other three
    # vendors, this is NOT a guarantee - see module docstring.
    computed_total = round(sum(
        float(r["amount"].replace(",", "")) for r in line_items if MONEY_RE.match(r["amount"])
    ), 2)
    full_text = "\n\n".join(all_text_pages)
    printed_total = None
    m = re.search(r"Total Balance\s*:?\s*\$?\s*([\d,]+\.\d{2})", full_text, re.IGNORECASE)
    if m:
        printed_total = float(m.group(1).replace(",", ""))

    recovered_count = sum(1 for r in line_items if r["recovered"])

    summary = dict(header_info)
    summary["amounts_refined_via_targeted_crop"] = f"{refined_count}/{len(line_items)}"
    summary["rows_recovered_from_gap_detection"] = recovered_count
    summary["total_computed_from_amount_column"] = f"{computed_total:,.2f}"
    summary["total_printed_if_found"] = f"{printed_total:,.2f}" if printed_total is not None else None
    summary["reconciles"] = (printed_total is not None and computed_total == printed_total)
    summary["caveat"] = ("Scanned/OCR'd document - amounts and dropped/garbled rows should be "
                          "spot-checked against the source scan, especially if 'reconciles' is "
                          "False or no printed total was found.")

    return {
        "line_items": line_items,
        "fieldnames": fieldnames,
        "summary": summary,
        "full_text": full_text,
    }


if __name__ == "__main__":
    import sys
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "KSI (Noakers) 053126.pdf"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
