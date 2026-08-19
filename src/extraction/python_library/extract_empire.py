"""
Extract Empire Auto Parts customer account statement PDF into:
  1. Empire Hewitt's - line items.csv  (structured transaction list)
  2. Empire Hewitt's - summary.csv     (header info + printed total balance)

This PDF has real embedded text (confirmed via pdfplumber probe - not a
scan), but pdfplumber's native extract_table() finds nothing usable here
(no ruled table lines for it to detect), so line items are reconstructed
from extract_words() using x0 column boundaries measured directly from
this document's word positions (transaction date / description / doc # /
your PO # / orig inv # / amount / due date / balance).
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["EMPIRE AUTO PARTS"]

ROW_TOLERANCE = 3.0

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
MONEY_RE = re.compile(r"^-?[\d,]+\.\d{2}$")
DOC_NO_RE = re.compile(r"^\d{7,9}$")

# Column boundaries (x0), measured from this document's word positions.
COLUMN_BOUNDS = [
    ("transaction_date", 0, 65),
    ("description", 65, 200),
    ("doc_no", 200, 260),
    ("your_po_no", 260, 325),
    ("orig_inv_no", 325, 420),
    ("amount", 420, 470),
    ("due_date", 470, 545),
    ("balance", 545, 10_000),
]


def bucket_column(x0):
    for name, lo, hi in COLUMN_BOUNDS:
        if lo <= x0 < hi:
            return name
    return None


def group_rows(words):
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
    m = re.search(r"(EMPIRE AUTO PARTS[^\n]*)\n([^\n]+)\n([^\n]+)\n", page1_text)
    if m:
        info["vendor_name"] = m.group(1).strip()
        info["vendor_address"] = m.group(2).strip()
        info["vendor_city_state_zip"] = m.group(3).strip()
    m = re.search(r"\n(\d{6})\n(VIVE[^\n]*)\n([^\n]+)\n([^\n]+)\n", page1_text)
    if m:
        info["account_no"] = m.group(1).strip()
        info["customer_name"] = m.group(2).strip()
        info["billing_address"] = m.group(3).strip()
        info["billing_city_state_zip"] = m.group(4).strip()
    m = re.search(r"Region:\s*(\S+)", page1_text)
    if m:
        info["region"] = m.group(1).strip()
    return info


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    line_items = []
    header_info = {}
    total_balance = None
    activity_through = None

    with pdfplumber.open(pdf_path) as pdf:
        header_info = parse_header_info(pdf.pages[0].extract_text() or "")

        for page_num, page in enumerate(pdf.pages, start=1):
            full_text = page.extract_text() or ""
            m = re.search(r"Total Balance:\s*\$([\d,.\-]+)", full_text)
            if m:
                total_balance = m.group(1)
            m = re.search(r"Activity through (\d{2}/\d{2}/\d{2})", full_text)
            if m:
                activity_through = m.group(1)

            words = page.extract_words()
            rows = group_rows(words)

            for row in rows:
                cols = {name: [] for name, _, _ in COLUMN_BOUNDS}
                for w in row:
                    col = bucket_column(w["x0"])
                    if col:
                        cols[col].append(w)

                transaction_date = " ".join(w["text"] for w in cols["transaction_date"])
                desc_words = sorted(cols["description"], key=lambda w: w["x0"])
                description = " ".join(w["text"] for w in desc_words)
                doc_no = " ".join(w["text"] for w in cols["doc_no"])

                # The doc number sometimes runs into the last description word
                # with no space (e.g. "Highlander40444218"), so pdfplumber
                # treats it as one token that lands entirely in the
                # description column - split it back out here.
                if not doc_no and desc_words:
                    m = re.search(r"(\d{7,9})$", desc_words[-1]["text"])
                    if m:
                        doc_no = m.group(1)
                        description = description[: -len(doc_no)].rstrip()
                your_po_no = " ".join(w["text"] for w in cols["your_po_no"])
                orig_inv_no = " ".join(w["text"] for w in cols["orig_inv_no"])
                amount = " ".join(w["text"] for w in cols["amount"])
                due_date = " ".join(w["text"] for w in cols["due_date"])
                balance = " ".join(w["text"] for w in cols["balance"])

                # A genuine transaction row has a transaction date and a doc number.
                if DATE_RE.match(transaction_date) and DOC_NO_RE.match(doc_no):
                    line_items.append({
                        "page": page_num,
                        "transaction_date": transaction_date,
                        "description": description,
                        "doc_no": doc_no,
                        "your_po_no": your_po_no,
                        "orig_inv_no": orig_inv_no,
                        "amount": amount,
                        "due_date": due_date if DATE_RE.match(due_date) else "",
                        "balance": balance,
                    })

    fieldnames = ["page", "transaction_date", "description", "doc_no", "your_po_no",
                  "orig_inv_no", "amount", "due_date", "balance"]

    computed_total = round(sum(float(r["amount"].replace(",", "")) for r in line_items if MONEY_RE.match(r["amount"])), 2)
    printed_total = float((total_balance or "0").replace(",", ""))

    summary = dict(header_info)
    summary["activity_through"] = activity_through
    summary["total_balance_printed"] = total_balance
    summary["total_balance_computed_from_amount_column"] = f"{computed_total:,.2f}"
    summary["reconciles"] = computed_total == printed_total

    return {
        "line_items": line_items,
        "fieldnames": fieldnames,
        "summary": summary,
        "full_text": None,
    }


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "Empire Hewitt's.PDF"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
