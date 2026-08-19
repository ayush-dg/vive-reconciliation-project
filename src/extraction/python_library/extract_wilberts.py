"""
Extract Wilbert's Inc. (auto-parts) customer account statement PDF into:
  1. Wilbert's Owego - line items.csv  (structured transaction list)
  2. Wilbert's Owego - summary.csv     (header info + printed Balance Due)

This PDF has real embedded text (confirmed via pdfplumber probe - not a
scan, no OCR needed). pdfplumber's native extract_table() finds a "table"
on the line-item page, but it collapses every row of a given column into
one newline-joined cell - and the Reference column sometimes wraps onto a
second physical line (a "DT#nnnnnn" debit-ticket continuation under a
credit-memo reference), so that column ends up with more newline-segments
than the Date/Invoice/Amount columns. Zipping table cells by line index
would silently misalign rows from that point on. So, as with the Fred
Beans / Empire statements, line items are reconstructed from
extract_words() using x0 column-boundary bucketing, with continuation
rows (a lone "DT#nnnnnn" token) merged back into the previous row's
Reference field.

The statement layout also mirrors every Invoice #/Balance pair a second
time far to the right (x0 ~480-580) as a tear-off remittance stub -
those duplicate columns are intentionally ignored.

Reconciliation note: the printed "Balance Due" equals the sum of the
*Balance* column, not the *Amount* column. For ordinary invoice/credit
rows Amount and Balance are identical, but the one "Payment" row (a
lump-sum payment applied across several invoices) has a non-zero Amount
(-$5,542.30, the payment total) and a Balance of $0.00 (the payment
itself carries no standalone outstanding balance - it was already
absorbed by the CR/credit rows for the invoices it paid down). Summing
Amount therefore double-counts the payment; summing Balance is what the
statement itself does, and is what is used for total_computed below.
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["Wilbert's Inc"]

ROW_TOLERANCE = 3.0

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
MONEY_RE = re.compile(r"^\(?\$[\d,]+\.\d{2}\)?$")
DT_CONTINUATION_RE = re.compile(r"^DT#\d+$")

# Column boundaries (x0), measured from this document's word positions.
# Columns beyond x0=460 are the duplicate remittance-stub Invoice #/Balance
# columns and are intentionally not bucketed (ignored).
COLUMN_BOUNDS = [
    ("date", 0, 85),
    ("store", 85, 100),
    ("invoice_number", 100, 156),
    ("reference", 156, 285),
    ("amount", 285, 335),
    ("core_chg", 335, 395),
    ("balance", 395, 460),
]

FIELDNAMES = ["page", "date", "store", "invoice_number", "reference", "amount", "core_chg", "balance"]


def bucket_column(x0):
    for name, lo, hi in COLUMN_BOUNDS:
        if lo <= x0 < hi:
            return name
    return None


def group_rows(words):
    """Group words into rows by their 'top' coordinate."""
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


def clean_money(raw):
    """'$320.20' -> '320.20', '($320.20)' -> '-320.20'."""
    s = raw.strip()
    if not s:
        return ""
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").replace(",", "")
    return f"-{s}" if neg else s


def parse_header_info(page1_words, page1_text):
    """The header has a left column (vendor info, statement date/account no,
    customer name/address) and a right column that duplicates most of it as
    a tear-off remittance stub. Because the two columns share near-identical
    'top' coordinates in places, plain extract_text() interleaves them onto
    the same line - so pull the left column (x0 < 250) out by word position
    instead, the same way parse_header_info does in extract_statement.py.
    """
    info = {}
    left_words = [w for w in page1_words if w["x0"] < 250]
    rows = group_rows(left_words)

    def row_text(row):
        return " ".join(w["text"] for w in sorted(row, key=lambda w: w["x0"]))

    # Vendor block: top ~30-95 -> "Wilbert's Inc.", "1272 Salt Road", "Webster NY 14580", phone
    vendor_lines = [row_text(r) for r in rows if 30 <= r[0]["top"] <= 95]
    if len(vendor_lines) >= 4:
        info["vendor_name"] = vendor_lines[0]
        info["vendor_address"] = vendor_lines[1]
        info["vendor_city_state_zip"] = vendor_lines[2]
        info["vendor_phone"] = vendor_lines[3]

    # Customer block: top ~165-215 -> name, address line, city/state/zip
    customer_lines = [row_text(r) for r in rows if 165 <= r[0]["top"] <= 215]
    if len(customer_lines) >= 3:
        info["customer_name"] = customer_lines[0]
        info["billing_address"] = customer_lines[1]
        info["billing_city_state_zip"] = customer_lines[2]

    m = re.search(r"Statement Date Account No\.\s*\n(\d{2}/\d{2}/\d{2})\s+(\d+)", page1_text)
    if m:
        info["statement_date"] = m.group(1)
        info["account_no"] = m.group(2)

    return info


def parse_printed_total(last_page_text):
    """The last "Balance Due" line on the final page carries the printed
    account total (appears again once more on the tear-off stub, same
    value both times)."""
    m = re.search(r"Balance Due\s*\n\$([\d,]+\.\d{2})", last_page_text)
    if m:
        return m.group(1)
    return None


def parse_aging_current(last_page_text):
    m = re.search(r"Balance Due\n\$([\d,]+\.\d{2})\nBalance Due", last_page_text)
    if m:
        return m.group(1)
    return None


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    line_items = []
    header_info = {}
    last_page_text = ""

    with pdfplumber.open(pdf_path) as pdf:
        header_info = parse_header_info(pdf.pages[0].extract_words(), pdf.pages[0].extract_text() or "")

        for page_num, page in enumerate(pdf.pages, start=1):
            last_page_text = page.extract_text() or ""
            words = page.extract_words()
            rows = group_rows(words)

            for row in rows:
                cols = {name: [] for name, _, _ in COLUMN_BOUNDS}
                for w in row:
                    col = bucket_column(w["x0"])
                    if col:
                        cols[col].append(w)

                date = " ".join(w["text"] for w in cols["date"])
                invoice_number = " ".join(w["text"] for w in sorted(cols["invoice_number"], key=lambda w: w["x0"]))
                amount = " ".join(w["text"] for w in cols["amount"])
                reference = " ".join(w["text"] for w in sorted(cols["reference"], key=lambda w: w["x0"]))
                core_chg = " ".join(w["text"] for w in cols["core_chg"])
                balance = " ".join(w["text"] for w in cols["balance"])
                store = " ".join(w["text"] for w in cols["store"])

                # A genuine transaction row has a transaction date and a money
                # amount. Header/label rows (e.g. the "Statement Date Account
                # No." block, which also matches the date regex) never carry
                # a matching amount token, so they're excluded here.
                if DATE_RE.match(date) and MONEY_RE.match(amount):
                    line_items.append({
                        "page": page_num,
                        "date": date,
                        "store": store,
                        "invoice_number": invoice_number,
                        "reference": reference,
                        "amount": clean_money(amount),
                        "core_chg": clean_money(core_chg),
                        "balance": clean_money(balance),
                    })
                elif DT_CONTINUATION_RE.match(reference.strip()) and line_items:
                    # Wrapped second line of a credit-memo reference, e.g.
                    # "CR for #1690264," followed on the next line by
                    # "DT#704518" - fold it back into the row above. The
                    # reference already ends with a comma in these cases,
                    # so just append with a space (no extra comma).
                    line_items[-1]["reference"] += " " + reference.strip()

    computed_total = round(sum(float(item["balance"]) for item in line_items if item["balance"]), 2)
    computed_amount_total = round(sum(float(item["amount"]) for item in line_items if item["amount"]), 2)

    printed_total_str = parse_printed_total(last_page_text)
    printed_total = float(printed_total_str.replace(",", "")) if printed_total_str else None

    summary = dict(header_info)
    summary["aging_current_printed"] = parse_aging_current(last_page_text)
    summary["total_balance_due_printed"] = printed_total_str
    summary["total_amount_column_computed"] = f"{computed_amount_total:,.2f}"
    summary["total_computed"] = f"{computed_total:,.2f}"
    summary["total_printed"] = printed_total_str
    summary["reconciles"] = printed_total is not None and computed_total == printed_total

    return {
        "line_items": line_items,
        "fieldnames": FIELDNAMES,
        "summary": summary,
        "full_text": None,
    }


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "Wilbert's Owego.PDF"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
