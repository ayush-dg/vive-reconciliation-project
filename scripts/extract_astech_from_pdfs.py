"""
Extract AsTech vendor line items from scanned NetSuite "A/P Payment History by
Payment" PDF reports and write them to an Excel workbook.

The source PDFs (in astech/) have NO text layer -- they were produced via
"Microsoft: Print to PDF" and the report content is rendered as vector
outlines, so PyMuPDF text extraction returns nothing. This script rasterizes
every page and OCRs it (RapidOCR, fully offline / no external Tesseract
binary needed), reconstructs the report's 5-column table
(TRANSACTION | BILL TYPE | DATE | DOCUMENT NUMBER | AMOUNT) from the OCR
bounding boxes, and keeps only the rows belonging to payment/credit groups
whose header or footer line mentions "AsTech".

Usage:
    python scripts/extract_astech_from_pdfs.py

Reads every *.pdf in the directory given by --input-dir (default: the
`astech` folder under the user's Downloads directory) and writes
astech_matches.xlsx into --output (default: same folder as this script's
project root).

Progress is cached page-by-page (as JSON) under a cache directory so a run
that gets interrupted can resume without re-OCRing pages already done.
"""

import argparse
import json
import re
from pathlib import Path

import fitz  # PyMuPDF
from rapidocr_onnxruntime import RapidOCR

# Column boundaries (in pixels) for a page rendered at 2x zoom (1224x1584).
# Derived from the report's own header row: BILL TYPE / DATE / DOCUMENT
# NUMBER / AMOUNT are right-aligned table columns; TRANSACTION is the wide
# free-text column on the left.
COL_BOUNDS = [
    ("transaction", 0, 645),
    ("bill_type", 645, 748),
    ("date", 748, 832),
    ("document_number", 832, 1072),
    ("amount", 1072, 10_000),
]

HEADER_ROW_WORDS = {"transaction", "bill", "type", "date", "document number", "amount"}

GROUP_HEADER_RE = re.compile(
    r"^(Bill Credit|Bill Payment|Bill|Check|Deposit|Journal|Credit Memo|Vendor Credit)\b.*#",
    re.IGNORECASE,
)
FOOTER_RE = re.compile(r"^Amount Unapplied", re.IGNORECASE)
ASTECH_RE = re.compile(r"as\s*-?\s*tech", re.IGNORECASE)

ZOOM = 2.0
ROW_Y_TOLERANCE = 10  # px, for clustering OCR boxes into the same table row


def ocr_page(engine, page):
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM))
    import numpy as np
    import cv2

    arr = np.frombuffer(pix.tobytes("png"), dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    result, _ = engine(img)
    boxes = []
    if result:
        for bbox, text, conf in result:
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            boxes.append(
                {
                    "x0": min(xs),
                    "x1": max(xs),
                    "y0": min(ys),
                    "y1": max(ys),
                    "text": text.strip(),
                    "conf": conf,
                }
            )
    return boxes


def cluster_rows(boxes):
    boxes = sorted(boxes, key=lambda b: (b["y0"] + b["y1"]) / 2)
    rows = []
    for b in boxes:
        cy = (b["y0"] + b["y1"]) / 2
        placed = False
        for row in rows:
            if abs(row["cy"] - cy) <= ROW_Y_TOLERANCE:
                row["boxes"].append(b)
                row["cy"] = (row["cy"] * row["n"] + cy) / (row["n"] + 1)
                row["n"] += 1
                placed = True
                break
        if not placed:
            rows.append({"cy": cy, "n": 1, "boxes": [b]})
    rows.sort(key=lambda r: r["cy"])
    return rows


def classify_row(row):
    cols = {name: [] for name, _, _ in COL_BOUNDS}
    for b in sorted(row["boxes"], key=lambda b: b["x0"]):
        for name, lo, hi in COL_BOUNDS:
            if lo <= b["x0"] < hi:
                cols[name].append(b["text"])
                break
    return {name: " ".join(vals).strip() for name, vals in cols.items()}


def is_page_furniture(cols):
    txn = cols["transaction"].strip().lower()
    if not txn and not any(cols[c] for c in ("bill_type", "date", "document_number", "amount")):
        return True
    if txn in HEADER_ROW_WORDS or txn in ("bill", "type"):
        return True
    if re.match(r"^\d{1,2}/\d{1,2}/\d{2,4},?\s*\d{1,2}:\d{2}", cols["transaction"]):
        return True
    if "netsuite.com" in txn or "reportrunner" in txn:
        return True
    if "payment history by payment" in txn:
        return True
    if re.match(r"^\d+\s*/\s*\d+$", txn):  # page x/y footer
        return True
    return False


def process_pdf(pdf_path, engine, cache_dir):
    cache_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    all_rows = []  # (page_number, cols dict) for every non-furniture row, in order
    for page_idx in range(len(doc)):
        cache_file = cache_dir / f"{pdf_path.stem}_p{page_idx:04d}.json"
        if cache_file.exists():
            page_rows = json.loads(cache_file.read_text(encoding="utf-8"))
        else:
            boxes = ocr_page(engine, doc[page_idx])
            rows = cluster_rows(boxes)
            page_rows = [classify_row(r) for r in rows]
            cache_file.write_text(json.dumps(page_rows, ensure_ascii=False), encoding="utf-8")
        for cols in page_rows:
            if not is_page_furniture(cols):
                all_rows.append((page_idx + 1, cols))
        print(f"  page {page_idx + 1}/{len(doc)} OCR'd ({len(page_rows)} raw rows)")
    return all_rows


def extract_astech_blocks(file_rows):
    """
    file_rows: list of (source_file, page, cols) in document order.
    Returns a list of matched detail-row dicts, plus a list of group summaries.
    """
    matches = []
    summaries = []
    current_header = None  # cols dict of the most recent group-header row
    current_is_astech = False
    current_page = None
    current_file = None

    for source_file, page, cols in file_rows:
        txn = cols["transaction"].strip()

        if GROUP_HEADER_RE.match(txn):
            current_header = txn
            current_is_astech = bool(ASTECH_RE.search(txn))
            current_page = page
            current_file = source_file
            if current_is_astech:
                matches.append(
                    {
                        "file": source_file,
                        "page": page,
                        "group_header": current_header,
                        "row_role": "group_header",
                        "bill_type": cols["bill_type"],
                        "date": cols["date"],
                        "document_number": cols["document_number"],
                        "amount": cols["amount"],
                    }
                )
            continue

        if FOOTER_RE.match(txn):
            is_astech = current_is_astech or bool(ASTECH_RE.search(txn))
            if is_astech:
                matches.append(
                    {
                        "file": source_file,
                        "page": page,
                        "group_header": current_header,
                        "row_role": "footer_amount_unapplied",
                        "bill_type": cols["bill_type"],
                        "date": cols["date"],
                        "document_number": cols["document_number"],
                        "amount": cols["amount"],
                    }
                )
                summaries.append(
                    {
                        "file": current_file,
                        "page": current_page,
                        "group_header": current_header,
                        "unapplied_amount": cols["amount"],
                    }
                )
            current_header = None
            current_is_astech = False
            continue

        # plain detail row (no label), belongs to the currently open group
        if current_is_astech and (cols["bill_type"] or cols["document_number"] or cols["amount"]):
            matches.append(
                {
                    "file": source_file,
                    "page": page,
                    "group_header": current_header,
                    "row_role": "detail",
                    "bill_type": cols["bill_type"],
                    "date": cols["date"],
                    "document_number": cols["document_number"],
                    "amount": cols["amount"],
                }
            )

    return matches, summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        default=str(Path.home() / "Downloads" / "astech"),
        help="Directory containing the source PDFs.",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parent.parent / "astech_matches.xlsx"),
        help="Path to the output .xlsx file.",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(Path(__file__).resolve().parent.parent / ".astech_ocr_cache"),
        help="Directory used to cache per-page OCR results so re-runs can resume.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    pdf_paths = sorted(input_dir.glob("*.pdf"))
    if not pdf_paths:
        raise SystemExit(f"No PDFs found in {input_dir}")

    engine = RapidOCR()
    cache_dir = Path(args.cache_dir)

    all_file_rows = []
    for pdf_path in pdf_paths:
        print(f"Processing {pdf_path.name} ...")
        rows = process_pdf(pdf_path, engine, cache_dir)
        for page, cols in rows:
            all_file_rows.append((pdf_path.name, page, cols))

    matches, summaries = extract_astech_blocks(all_file_rows)
    print(f"Found {len(matches)} AsTech detail/header/footer rows across "
          f"{len(summaries)} payment groups.")

    import pandas as pd

    detail_df = pd.DataFrame(matches, columns=[
        "file", "page", "group_header", "row_role",
        "bill_type", "date", "document_number", "amount",
    ])
    summary_df = pd.DataFrame(summaries, columns=[
        "file", "page", "group_header", "unapplied_amount",
    ])

    output_path = Path(args.output)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        detail_df.to_excel(writer, sheet_name="AsTech Detail", index=False)
        summary_df.to_excel(writer, sheet_name="AsTech Group Summary", index=False)

    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
