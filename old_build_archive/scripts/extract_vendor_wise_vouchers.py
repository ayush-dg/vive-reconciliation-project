"""
Extract line-item data from the "Payment Voucher" PDFs in
astech/vendor_wise/ (one PDF per vendor: ASTECH, Fred Beans, KSI) and write
one Excel workbook per PDF.

These vouchers have a real text layer (unlike the older "by Payment"
reports), so no OCR is needed. Each voucher lists, for one check/payment,
every Bill / Bill Credit line applied to it:
    Date | Description | Orig. Amount | Amount Due | Discount | Applied Amount
The column header row repeats on every page; line items follow it until
the next page break or the final "Amount  $X" grand-total line.

Usage:
    python scripts/extract_vendor_wise_vouchers.py
"""

import argparse
import re
from pathlib import Path

import fitz  # PyMuPDF

DATE_MAX_X = 100
DESCRIPTION_MAX_X = 260
ORIG_AMOUNT_MAX_X = 340
AMOUNT_DUE_MAX_X = 410
DISCOUNT_MAX_X = 485
# APPLIED_AMOUNT: x0 >= DISCOUNT_MAX_X

ROW_Y_TOLERANCE = 3.0

DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


def cluster_rows(words):
    """words: list of (x0, y0, text). Returns rows sorted top-to-bottom,
    each a list of (x0, text) sorted left-to-right."""
    rows = []
    for x0, y0, text in sorted(words, key=lambda w: w[1]):
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


def bucket_row(row_words):
    cols = {"date": [], "description": [], "orig_amount": [], "amount_due": [], "discount": [], "applied_amount": []}
    for x0, text in row_words:
        if x0 < DATE_MAX_X:
            cols["date"].append(text)
        elif x0 < DESCRIPTION_MAX_X:
            cols["description"].append(text)
        elif x0 < ORIG_AMOUNT_MAX_X:
            cols["orig_amount"].append(text)
        elif x0 < AMOUNT_DUE_MAX_X:
            cols["amount_due"].append(text)
        elif x0 < DISCOUNT_MAX_X:
            cols["discount"].append(text)
        else:
            cols["applied_amount"].append(text)
    return {k: " ".join(v).strip() for k, v in cols.items()}


def extract_header_info(first_page_text):
    vendor_match = re.search(r"Paid To\n(.+)", first_page_text)
    date_match = re.search(r"Payment Voucher\nDate\n(\d{1,2}/\d{1,2}/\d{4})", first_page_text)
    check_match = re.search(r"Check #\n?\s*(\S+)", first_page_text)
    return {
        "vendor": vendor_match.group(1).strip() if vendor_match else None,
        "voucher_date": date_match.group(1) if date_match else None,
        "check_number": check_match.group(1) if check_match else None,
    }


def extract_voucher(pdf_path):
    doc = fitz.open(pdf_path)
    header_info = extract_header_info(doc[0].get_text())

    line_items = []
    grand_total = None

    for page_idx in range(len(doc)):
        words = [(w[0], w[1], w[4]) for w in doc[page_idx].get_text("words")]
        rows = cluster_rows(words)

        header_row_idx = None
        for i, row in enumerate(rows):
            cols = bucket_row(row["words"])
            if cols["date"] == "Date" and cols["description"] == "Description":
                header_row_idx = i
                break

        if header_row_idx is None:
            continue

        for row in rows[header_row_idx + 1:]:
            cols = bucket_row(row["words"])
            if DATE_RE.match(cols["date"]) and cols["description"]:
                line_items.append(
                    {
                        "file": pdf_path.name,
                        "page": page_idx + 1,
                        "date": cols["date"],
                        "description": cols["description"],
                        "orig_amount": cols["orig_amount"],
                        "amount_due": cols["amount_due"],
                        "discount": cols["discount"],
                        "applied_amount": cols["applied_amount"],
                    }
                )
            elif cols["discount"] == "Amount" and cols["applied_amount"].startswith("$"):
                grand_total = cols["applied_amount"]

    return header_info, line_items, grand_total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        default=str(Path.home() / "Downloads" / "astech" / "vendor_wise"),
        help="Directory containing the vendor voucher PDFs.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent.parent),
        help="Directory to write one .xlsx per input PDF.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    pdf_paths = sorted(input_dir.glob("*.pdf"))
    if not pdf_paths:
        raise SystemExit(f"No PDFs found in {input_dir}")

    import pandas as pd

    for pdf_path in pdf_paths:
        print(f"Processing {pdf_path.name} ...")
        header_info, line_items, grand_total = extract_voucher(pdf_path)
        print(f"  vendor={header_info['vendor']!r} date={header_info['voucher_date']!r} "
              f"check#={header_info['check_number']!r} rows={len(line_items)} total={grand_total!r}")

        detail_df = pd.DataFrame(line_items, columns=[
            "file", "page", "date", "description",
            "orig_amount", "amount_due", "discount", "applied_amount",
        ])
        summary_df = pd.DataFrame([{
            "file": pdf_path.name,
            "vendor": header_info["vendor"],
            "voucher_date": header_info["voucher_date"],
            "check_number": header_info["check_number"],
            "line_item_count": len(line_items),
            "grand_total": grand_total,
        }])

        out_stem = re.sub(r"[^\w\-]+", "_", pdf_path.stem).strip("_")
        output_path = output_dir / f"voucher_{out_stem}.xlsx"
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="Voucher Summary", index=False)
            detail_df.to_excel(writer, sheet_name="Line Items", index=False)
        print(f"  Wrote {output_path}")


if __name__ == "__main__":
    main()
