"""
Extract ABC Parts International, Inc. customer account statement PDF into:
  1. <stem> - line items.csv  (structured transaction list)
  2. <stem> - summary.csv     (header info + printed Amount Due)

This PDF has real embedded text (confirmed via pdfplumber probe - not a
scan). pdfplumber's native extract_tables() finds only the header row (and
the aging-bucket header/values row) - it can't reconstruct the body rows
because they aren't ruled, so line items are built from extract_words()
using x0 column-boundary bucketing, the same technique used in
extract_empire.py / extract_wilberts.py.

Each transaction is TWO OR THREE physical lines: the main line (date, PO
number, "Sales Order" or "Credit Memo", description, original amount,
remaining balance, credit, running balance), followed directly beneath it
by the SO reference number continuation (e.g. "#C6988728") in the SO
Number column - except Credit Memo rows, which have no SO reference line
at all. A few of those rows carry a THIRD physical line beneath the "#..."
reference - a lone short token (e.g. "T", "S", "6") that is itself part of
the same SO reference (confirmed real data, not a rendering artifact - see
2026-09-02 correction). Both continuation lines fold into the SO Number
field of the row above, in order, e.g. "Sales Order #C7305991 T".

Reconciliation: printed "Amount Due" (top of statement) equals the last
row's running Balance, which is also confirmed against the aging-bucket
table's own "Amount Due" total at the bottom of the page.
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["ABC Parts International"]

ROW_TOLERANCE = 3.0

DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
MONEY_RE = re.compile(r"^-?\$[\d,]+\.\d{2}$")
SO_REF_RE = re.compile(r"^#\S+$")
# A bare short continuation token (e.g. "T", "S", "6") that can follow an
# already-appended "#..." reference line for the same row - excludes
# anything that could instead be a date or money token slipping through.
SHORT_TOKEN_RE = re.compile(r"^[A-Za-z0-9]{1,3}$")
INVOICE_NO_RE = re.compile(r"#(INV\d+|CM\d+|SO\d+)")

# Column boundaries (x0), measured from this document's word positions.
COLUMN_BOUNDS = [
    ("date", 0, 90),
    ("po_number", 90, 150),
    ("so_number", 150, 210),
    ("description", 210, 350),
    ("original_amount", 350, 395),
    ("remaining_balance", 395, 465),
    ("credit", 465, 520),
    ("balance", 520, 10_000),
]

FIELDNAMES = ["page", "date", "po_number", "so_number", "description", "invoice_number",
              "original_amount", "remaining_balance", "credit", "balance"]


def bucket_column(x0):
    for name, lo, hi in COLUMN_BOUNDS:
        if lo <= x0 < hi:
            return name
    return None


def clean_money(raw):
    """'$352.00' -> '352.00', '-' -> ''."""
    s = raw.strip()
    if not s or s == "-":
        return ""
    return s.replace("$", "").replace(",", "")


def group_rows(words):
    rows = []
    current_top = None
    current_row = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if current_top is None or abs(w["top"] - current_top) <= ROW_TOLERANCE:
            current_row.append(w)
            current_top = w["top"] if current_top is None else current_top
        else:
            rows.append(current_row)
            current_row = [w]
            current_top = w["top"]
    if current_row:
        rows.append(current_row)
    return rows


def parse_header_info(page1_words):
    rows = group_rows(page1_words)

    def row_text(row):
        return " ".join(w["text"] for w in sorted(row, key=lambda w: w["x0"]))

    info = {}
    vendor_rows = [r for r in rows if 30 <= r[0]["top"] <= 80 and r[0]["x0"] < 300]
    vendor_lines = [row_text(r) for r in vendor_rows]
    if len(vendor_lines) >= 3:
        info["vendor_name"] = vendor_lines[0].replace(" Statement", "")
        info["vendor_address"] = vendor_lines[1]
        info["vendor_city_state_zip"] = vendor_lines[2]

    # top ~120.7 is the "Billing Address" label itself; the actual
    # name/address/city block starts on the next line, ~130.5.
    billing_rows = [r for r in rows if 125 <= r[0]["top"] <= 160 and r[0]["x0"] < 250]
    billing_lines = [row_text(r) for r in billing_rows]
    if len(billing_lines) >= 3:
        info["customer_name"] = billing_lines[0]
        info["billing_address"] = billing_lines[1]
        info["billing_city_state_zip"] = billing_lines[2]

    for w in page1_words:
        if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", w["text"]) and w["x0"] > 450 and w["top"] < 80:
            info["statement_date"] = w["text"]
            break

    for r in rows:
        texts = [w["text"] for w in r]
        if len(texts) == 1 and re.match(r"^\d{2}-[A-Z0-9]+$", texts[0]):
            info["account_no"] = texts[0]
            break

    return info


def parse_amount_due(page1_text):
    m = re.search(r"Amount Due\s*\n\$([\d,]+\.\d{2})", page1_text)
    return m.group(1) if m else None


def parse_aging_summary(words):
    rows = group_rows(words)
    header_row = None
    for row in rows:
        texts = {w["text"] for w in row}
        if "Current" in texts and "Amount" in texts and "Due" in texts:
            header_row = row
            break
    if header_row is None:
        return {}

    anchors = {}
    for w in header_row:
        if w["text"] == "Current":
            anchors["aging_current"] = w["x0"]
        elif w["text"] == "1-30":
            anchors["aging_1_30"] = w["x0"]
        elif w["text"] == "31-60":
            anchors["aging_31_60"] = w["x0"]
        elif w["text"] == "61-90":
            anchors["aging_61_90"] = w["x0"]
        elif w["text"] == "Over":
            anchors["aging_over_90"] = w["x0"]
        elif w["text"] == "Amount":
            anchors["aging_amount_due_printed"] = w["x0"]

    header_top = header_row[0]["top"]
    result = {name: None for name in anchors}
    for row in rows:
        row_top = row[0]["top"]
        if row_top <= header_top or row_top > header_top + 25:
            continue
        for w in row:
            if not MONEY_RE.match(w["text"]):
                continue
            for name, anchor_x0 in anchors.items():
                if result[name] is None and abs(w["x0"] - anchor_x0) < 15:
                    result[name] = clean_money(w["text"])
    return result


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    line_items = []
    header_info = {}
    amount_due_printed = None
    last_page_words = []

    with pdfplumber.open(pdf_path) as pdf:
        page1_words = pdf.pages[0].extract_words()
        header_info = parse_header_info(page1_words)
        amount_due_printed = parse_amount_due(pdf.pages[0].extract_text() or "")

        for page_num, page in enumerate(pdf.pages, start=1):
            words = page.extract_words()
            last_page_words = words
            rows = group_rows(words)

            # True only right after a "#..." SO-reference continuation line
            # has been appended to the current row - lets a following bare
            # short token (e.g. "T") be recognized as that same reference's
            # own continuation rather than an unrelated stray token. Reset
            # on every new date row and on any other kind of line.
            last_was_so_ref = False

            for row in rows:
                cols = {name: [] for name, _, _ in COLUMN_BOUNDS}
                for w in row:
                    col = bucket_column(w["x0"])
                    if col:
                        cols[col].append(w)

                date = " ".join(w["text"] for w in cols["date"])

                if DATE_RE.match(date):
                    description = " ".join(w["text"] for w in sorted(cols["description"], key=lambda w: w["x0"]))
                    so_number = " ".join(w["text"] for w in sorted(cols["so_number"], key=lambda w: w["x0"]))
                    m = INVOICE_NO_RE.search(description)
                    invoice_number = m.group(1) if m else ""

                    line_items.append({
                        "page": page_num,
                        "date": date,
                        "po_number": " ".join(w["text"] for w in cols["po_number"]),
                        "so_number": so_number,
                        "description": description,
                        "invoice_number": invoice_number,
                        "original_amount": clean_money(" ".join(w["text"] for w in cols["original_amount"])),
                        "remaining_balance": clean_money(" ".join(w["text"] for w in cols["remaining_balance"])),
                        "credit": clean_money(" ".join(w["text"] for w in cols["credit"])),
                        "balance": clean_money(" ".join(w["text"] for w in cols["balance"])),
                    })
                    last_was_so_ref = False
                    continue

                # Continuation line: only the SO-reference number (or, on
                # some rows, a further short token continuing that same
                # reference), directly beneath the "Sales Order" / "Credit
                # Memo" line above.
                so_only = [w for w in row if bucket_column(w["x0"]) == "so_number"]
                other_cols = [w for w in row if bucket_column(w["x0"]) not in (None, "so_number")]
                if so_only and not other_cols and line_items:
                    text = " ".join(w["text"] for w in sorted(so_only, key=lambda w: w["x0"]))
                    if SO_REF_RE.match(text):
                        line_items[-1]["so_number"] += " " + text
                        last_was_so_ref = True
                    elif last_was_so_ref and SHORT_TOKEN_RE.match(text):
                        line_items[-1]["so_number"] += " " + text
                        # last_was_so_ref stays True: a further short token
                        # could in principle continue again.
                    else:
                        last_was_so_ref = False

    fieldnames = FIELDNAMES

    def to_float(s):
        return float(s) if s else 0.0

    computed_total = round(sum(to_float(r["balance"]) for r in line_items), 2)
    # Last row's running balance is the statement's own running total.
    last_balance = to_float(line_items[-1]["balance"]) if line_items else None
    printed_total = float(amount_due_printed.replace(",", "")) if amount_due_printed else None

    summary = dict(header_info)
    summary["amount_due_printed"] = amount_due_printed
    summary["last_row_balance"] = f"{last_balance:,.2f}" if last_balance is not None else None
    summary["reconciles"] = printed_total is not None and last_balance == printed_total
    summary.update(parse_aging_summary(last_page_words))

    return {
        "line_items": line_items,
        "fieldnames": fieldnames,
        "summary": summary,
        "full_text": None,
    }


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "ABCCR0826.pdf"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
    for item in result["line_items"]:
        print(item)
