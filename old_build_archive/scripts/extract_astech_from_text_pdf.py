"""
Extract AsTech vendor line items from the "A/P Payment History by Bill"
NetSuite PDF export (astech/newjun1-6.pdf) and write them to an Excel
workbook.

Unlike the older "by Payment" exports, this PDF has a real text layer
(it was saved via a browser's Save-as-PDF, not "Print to PDF"), so no OCR
is needed -- PyMuPDF's word-level text extraction is used directly.

Report layout: each "block" of text on a page is either
  - a header+detail block: "Bill #<doc> - <Vendor>" followed by one or more
    detail rows (PAYMENT TYPE | DATE | DOCUMENT NUMBER | AMOUNT), or
  - a footer block: "Amount Due - Bill #<doc> - <Vendor>" + a single
    AMOUNT value.
Vendor names can wrap onto a second physical line within the same block,
so the label text is reassembled from every word left of the data columns
across all lines in the block.

Usage:
    python scripts/extract_astech_from_text_pdf.py
"""

import argparse
import re
from collections import defaultdict
from pathlib import Path

import fitz  # PyMuPDF

# Column x0 boundaries (PDF points, unscaled -- this file has a real text
# layer so no zoom/rasterization is involved).
TRANSACTION_MAX_X = 280
PAYMENT_TYPE_MAX_X = 345
DATE_MAX_X = 385
DOCUMENT_NUMBER_MAX_X = 510

HEADER_RE = re.compile(
    r"^(Bill Credit|Bill Payment|Bill|Check|Deposit|Journal|Credit Memo|Vendor Credit)\b.*#",
    re.IGNORECASE,
)
FOOTER_RE = re.compile(r"^Amount Due\b", re.IGNORECASE)
ASTECH_RE = re.compile(r"(?<![a-z])as[\s-]?tech(?![a-z])", re.IGNORECASE)


ROW_Y_TOLERANCE = 3.0  # points; groups words from the same visual table row


def page_blocks(page):
    """Group words into blocks -> ordered list of (x0, y0, text) word tuples."""
    words = page.get_text("words")  # x0,y0,x1,y1,text,block_no,line_no,word_no
    blocks = defaultdict(list)
    block_y = {}
    for x0, y0, x1, y1, text, block_no, line_no, word_no in words:
        blocks[block_no].append((x0, y0, text))
        block_y[block_no] = min(block_y.get(block_no, y0), y0)

    ordered_block_nos = sorted(blocks.keys(), key=lambda b: block_y[b])
    return [blocks[b] for b in ordered_block_nos]


def cluster_visual_rows(block_words):
    """Cluster a block's words by y-coordinate into physical table rows."""
    rows = []
    for x0, y0, text in sorted(block_words, key=lambda w: w[1]):
        placed = False
        for row in rows:
            if abs(row["y"] - y0) <= ROW_Y_TOLERANCE:
                row["words"].append((x0, text))
                row["y"] = (row["y"] * row["n"] + y0) / (row["n"] + 1)
                row["n"] += 1
                placed = True
                break
        if not placed:
            rows.append({"y": y0, "n": 1, "words": [(x0, text)]})
    rows.sort(key=lambda r: r["y"])
    for row in rows:
        row["words"].sort(key=lambda w: w[0])
    return rows


def classify_block(block_words):
    """Return dict describing this block: label_text, kind, detail_rows, footer_amount."""
    label_words = []
    detail_rows = []
    footer_amount_words = []

    for row in cluster_visual_rows(block_words):
        label_part = [w for w in row["words"] if w[0] < TRANSACTION_MAX_X]
        data_part = [w for w in row["words"] if w[0] >= TRANSACTION_MAX_X]
        label_words.extend(w[1] for w in label_part)

        if data_part:
            payment_type, date, doc, amount = [], [], [], []
            for x0, text in data_part:
                if x0 < PAYMENT_TYPE_MAX_X:
                    payment_type.append(text)
                elif x0 < DATE_MAX_X:
                    date.append(text)
                elif x0 < DOCUMENT_NUMBER_MAX_X:
                    doc.append(text)
                else:
                    amount.append(text)
            if amount and not (payment_type or date or doc):
                footer_amount_words.extend(amount)
            else:
                detail_rows.append(
                    {
                        "payment_type": " ".join(payment_type),
                        "date": " ".join(date),
                        "document_number": " ".join(doc),
                        "amount": " ".join(amount),
                    }
                )

    label_text = " ".join(label_words).strip()
    if HEADER_RE.match(label_text):
        kind = "header"
    elif FOOTER_RE.match(label_text):
        kind = "footer"
    else:
        kind = "other"

    return {
        "label_text": label_text,
        "kind": kind,
        "detail_rows": detail_rows,
        "footer_amount": " ".join(footer_amount_words).strip(),
    }


def extract_file_blocks(pdf_path):
    doc = fitz.open(pdf_path)
    for page_idx in range(len(doc)):
        for block_lines in page_blocks(doc[page_idx]):
            info = classify_block(block_lines)
            if info["kind"] != "other":
                yield page_idx + 1, info


def extract_astech_matches(files_and_blocks):
    """files_and_blocks: iterable of (filename, page, block_info) in doc order."""
    matches = []
    summaries = []
    current_label = None
    current_is_astech = False
    current_file = None
    current_page = None

    for filename, page, info in files_and_blocks:
        if info["kind"] == "header":
            current_label = info["label_text"]
            current_is_astech = bool(ASTECH_RE.search(current_label))
            current_file, current_page = filename, page
            if current_is_astech:
                matches.append(
                    {
                        "file": filename,
                        "page": page,
                        "group_header": current_label,
                        "row_role": "group_header",
                        "payment_type": "",
                        "date": "",
                        "document_number": "",
                        "amount": "",
                    }
                )
                for row in info["detail_rows"]:
                    matches.append(
                        {
                            "file": filename,
                            "page": page,
                            "group_header": current_label,
                            "row_role": "detail",
                            **row,
                        }
                    )
            continue

        if info["kind"] == "footer":
            label = info["label_text"]
            is_astech = current_is_astech or bool(ASTECH_RE.search(label))
            if is_astech:
                matches.append(
                    {
                        "file": filename,
                        "page": page,
                        "group_header": current_label or label,
                        "row_role": "footer_amount_due",
                        "payment_type": "",
                        "date": "",
                        "document_number": "",
                        "amount": info["footer_amount"],
                    }
                )
                summaries.append(
                    {
                        "file": current_file or filename,
                        "page": current_page or page,
                        "group_header": current_label or label,
                        "amount_due": info["footer_amount"],
                    }
                )
            current_label = None
            current_is_astech = False
            continue

    return matches, summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        default=str(Path.home() / "Downloads" / "astech"),
        help="Directory containing the source PDF(s).",
    )
    parser.add_argument(
        "--pattern",
        default="newjun1-6.pdf",
        help="Glob pattern (relative to --input-dir) selecting which PDFs to process.",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parent.parent / "astech_matches_by_bill.xlsx"),
        help="Path to the output .xlsx file.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    pdf_paths = sorted(input_dir.glob(args.pattern))
    if not pdf_paths:
        raise SystemExit(f"No PDFs matching {args.pattern!r} found in {input_dir}")

    all_blocks = []
    for pdf_path in pdf_paths:
        print(f"Processing {pdf_path.name} ...")
        for page, info in extract_file_blocks(pdf_path):
            all_blocks.append((pdf_path.name, page, info))
        print(f"  {len(all_blocks)} relevant blocks so far")

    matches, summaries = extract_astech_matches(all_blocks)
    print(f"Found {len(matches)} AsTech rows across {len(summaries)} bill groups.")

    import pandas as pd

    detail_df = pd.DataFrame(matches, columns=[
        "file", "page", "group_header", "row_role",
        "payment_type", "date", "document_number", "amount",
    ])
    summary_df = pd.DataFrame(summaries, columns=[
        "file", "page", "group_header", "amount_due",
    ])

    output_path = Path(args.output)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        detail_df.to_excel(writer, sheet_name="AsTech Detail", index=False)
        summary_df.to_excel(writer, sheet_name="AsTech Bill Summary", index=False)

    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()