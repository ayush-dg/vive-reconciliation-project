"""
Extract All Star Auto Lights, Inc. customer account statement PDF into:
  1. <stem> - line items.csv  (structured transaction list)
  2. <stem> - summary.csv     (header info + printed Amount Due)

This PDF has real embedded text (confirmed via pdfplumber probe on 5 real
August 2026 statements - Nutley, Middletown, Lees, JC, Quonset - not a
scan). The table isn't ruled, so line items are built from extract_words()
using x0 column-boundary bucketing, the same technique used in
extract_abc.py / extract_empire.py.

Columns: Date | Due Date | Transaction type | PO#/Ck# | Invoice |
Pymt/Credit | Open Balance. Two easy-to-misread things about this layout:
- The column headed "Invoice" is an AMOUNT (the invoice's original
  amount), not an identifier. The invoice NUMBER is printed inside the
  "Transaction type" column itself, e.g. "Invoice #S112612194" - split
  here into transaction_type ("Invoice") and invoice_number
  ("S112612194"). That number is the NetSuite vendorbill tranid verbatim
  (confirmed live against bronze.netsuite_vendorbill: 15 of 21 real
  invoice lines tie out exactly under entities 60731/4950; the other 6
  aren't in NetSuite under any entity), so no normalization rule is needed.
- A Payment row spans several physical lines in the Transaction type
  column: "Payment", then its own "#PYMT..." reference, then a free-text
  note (e.g. "Inv 1868342P pd w/ CM 1882723P $1343.00"). The "#..." line
  becomes that row's invoice_number (the row's only identifier); the
  rest is kept in memo.

Money is printed "$1,490.00", negatives in parentheses "($2,743.00)" -
normalized to "1490.00" / "-2743.00". A blank cell is None, NOT "" - a ""
raw value reaches Silver as a non-null charge_amount_raw and makes
dbt's sign-based line_type call a payment/credit row a CHARGE (see
models/silver/statement_line.sql's with_line_type CTE).

Reconciliation: the printed "Amount Due" (top right) equals the sum of
every row's Open Balance, and the aging table's own "Amount Due" total at
the bottom. Invoice minus Pymt/Credit does NOT reconcile on its own - a
Payment row's Open Balance is only the unapplied part of the payment
(Nutley: a $2,743.00 payment with $1,343.00 still open).
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["All Star Auto Lights"]

ROW_TOLERANCE = 3.0

DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
MONEY_RE = re.compile(r"^\(?-?\$[\d,]+\.\d{2}\)?$")

# Column boundaries (x0), measured from this layout's header/word positions.
COLUMN_BOUNDS = [
    ("date", 0, 100),
    ("due_date", 100, 165),
    ("transaction_type", 165, 275),
    ("po_number", 275, 370),
    ("invoice_amount", 370, 438),
    ("pymt_credit", 438, 505),
    ("open_balance", 505, 10_000),
]

FIELDNAMES = ["page", "date", "due_date", "transaction_type", "invoice_number", "po_number",
              "invoice_amount", "pymt_credit", "open_balance", "memo"]

AGING_ANCHORS = {
    "Current": "aging_current",
    "1-30": "aging_1_30",
    "31-60": "aging_31_60",
    "61-90": "aging_61_90",
    "Over": "aging_over_90",
    "Amount": "aging_amount_due_printed",
}


def bucket_column(x0):
    for name, lo, hi in COLUMN_BOUNDS:
        if lo <= x0 < hi:
            return name
    return None


def clean_money(raw):
    """'$1,490.00' -> '1490.00', '($2,743.00)' -> '-2743.00', '' -> None."""
    s = (raw or "").strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").replace(",", "")
    return f"-{s}" if negative else s


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


def row_text(row):
    return " ".join(w["text"] for w in sorted(row, key=lambda w: w["x0"]))


def is_table_header(row):
    texts = {w["text"] for w in row}
    return "Transaction" in texts and "Pymt/Credit" in texts


def is_aging_header(row):
    texts = {w["text"] for w in row}
    return "Current" in texts and "Amount" in texts and "Due" in texts


def parse_header_info(page1_text, page1_words):
    info = {}
    m = re.search(r"Statement Date:\s*(\d{1,2}/\d{1,2}/\d{4})", page1_text)
    if m:
        info["statement_date"] = m.group(1)
    # First "Account #" is the customer account; the second is the
    # vendor's own bank account number in the Pay Via ACH block.
    m = re.search(r"Account #\s*([A-Z]\d+)", page1_text)
    if m:
        info["account_no"] = m.group(1)

    # Billing block: left-hand lines between the "Billing Address" label
    # and the "Customer #..." line, excluding the remit-to column on the
    # right (x0 >= 400) and the trailing "United States" line.
    rows = group_rows(page1_words)
    label_top = next((r[0]["top"] for r in rows if row_text(r).startswith("Billing Address")), None)
    customer_top = next((r[0]["top"] for r in rows if row_text(r).startswith("Customer #")), None)
    if label_top is not None and customer_top is not None:
        lines = []
        for r in rows:
            if label_top < r[0]["top"] < customer_top:
                left = [w for w in r if w["x0"] < 400]
                text = row_text(left)
                if text and text != "United States":
                    lines.append(text)
        if len(lines) >= 3:
            info["customer_name"] = lines[0]
            info["billing_address"] = lines[1]
            info["billing_city_state_zip"] = lines[2]
    return info


def parse_amount_due(page1_text):
    m = re.search(r"Amount Due\s*\n\$([\d,]+\.\d{2})", page1_text)
    return m.group(1) if m else None


def parse_aging_summary(words):
    rows = group_rows(words)
    header_row = next((r for r in rows if is_aging_header(r)), None)
    if header_row is None:
        return {}

    anchors = {AGING_ANCHORS[w["text"]]: w["x0"] for w in header_row if w["text"] in AGING_ANCHORS}
    header_top = header_row[0]["top"]
    result = {name: None for name in anchors}
    for row in rows:
        if not (header_top < row[0]["top"] <= header_top + 25):
            continue
        for w in row:
            if not MONEY_RE.match(w["text"]):
                continue
            for name, anchor_x0 in anchors.items():
                if result[name] is None and abs(w["x0"] - anchor_x0) < 15:
                    result[name] = clean_money(w["text"])
    return result


def parse_main_row(cols, page_num):
    def text(name):
        return " ".join(w["text"] for w in sorted(cols[name], key=lambda w: w["x0"]))

    # "Invoice #S112612194" -> type "Invoice", number "S112612194";
    # "Payment" -> type "Payment", number filled from its "#..."
    # continuation line (see extract()).
    txn = text("transaction_type")
    m = re.match(r"^(.*?)\s*#(\S+)$", txn)
    transaction_type, invoice_number = (m.group(1), m.group(2)) if m else (txn, None)

    return {
        "page": page_num,
        "date": text("date"),
        "due_date": text("due_date") or None,
        "transaction_type": transaction_type or None,
        "invoice_number": invoice_number,
        "po_number": text("po_number") or None,
        "invoice_amount": clean_money(text("invoice_amount")),
        "pymt_credit": clean_money(text("pymt_credit")),
        "open_balance": clean_money(text("open_balance")),
        "memo": None,
    }


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    line_items = []
    aging = {}

    with pdfplumber.open(pdf_path) as pdf:
        page1 = pdf.pages[0]
        page1_text = page1.extract_text() or ""
        header_info = parse_header_info(page1_text, page1.extract_words())
        amount_due_printed = parse_amount_due(page1_text)

        for page_num, page in enumerate(pdf.pages, start=1):
            words = page.extract_words()
            rows = group_rows(words)

            # Only rows between this page's table header and the aging
            # table (or the page footer, on a continued page) are
            # transactions.
            in_table = False
            for row in rows:
                if is_table_header(row):
                    in_table = True
                    continue
                if is_aging_header(row):
                    in_table = False
                    continue
                if not in_table:
                    continue

                cols = {name: [] for name, _, _ in COLUMN_BOUNDS}
                for w in row:
                    col = bucket_column(w["x0"])
                    if col:
                        cols[col].append(w)

                if DATE_RE.match(" ".join(w["text"] for w in cols["date"])):
                    line_items.append(parse_main_row(cols, page_num))
                    continue

                # Continuation line (Payment rows): a "#..." reference
                # becomes the row's identifier if it has none yet;
                # anything else is free-text note.
                if not line_items:
                    continue
                text = row_text(row)
                last = line_items[-1]
                if last["invoice_number"] is None and re.match(r"^#\S+$", text):
                    last["invoice_number"] = text[1:]
                else:
                    last["memo"] = f"{last['memo']} {text}" if last["memo"] else text

            aging = parse_aging_summary(words) or aging

    def to_float(s):
        return float(s) if s else 0.0

    computed_total = round(sum(to_float(r["open_balance"]) for r in line_items), 2)
    printed_total = float(amount_due_printed.replace(",", "")) if amount_due_printed else None

    summary = dict(header_info)
    summary["amount_due_printed"] = amount_due_printed
    summary["total_computed"] = f"{computed_total:,.2f}"
    summary["reconciles"] = printed_total is not None and computed_total == printed_total
    summary.update(aging)

    return {
        "line_items": line_items,
        "fieldnames": FIELDNAMES,
        "summary": summary,
        "full_text": None,
    }


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "All Star Auto Lights, Nutley, Aug 26.pdf"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
    for item in result["line_items"]:
        print(item)
