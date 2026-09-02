"""
Extract Rivian, LLC customer account statement PDF into:
  1. <stem> - line items.csv  (structured transaction list)
  2. <stem> - summary.csv     (header info + printed Total)

Unlike every other vendor in this folder, this PDF has a genuinely ruled
table pdfplumber's extract_table() reconstructs correctly on its own - no
x0/x1 word-position bucketing is needed here. The one quirk: the table's
5th column header cell is blank (None) in every row, an unlabeled spacer
between "Invoice Amount" and "Net Due Date" that never carries a value in
any row - dropped rather than kept as a meaningless field.

The table's first data row is always "Opening Balance" (no date/order/
invoice, just a starting balance - $0.00 on this statement) - excluded
from line_items (not a real transaction) and reported in summary instead,
the same convention extract_precision.py uses for its own "Balance
Forward" row. The table's last row is always "Total" (column totals, not
a transaction) - excluded from line_items and used as the printed total
for reconciliation instead.

One row (08/19/2026 here) is a credit/adjustment with no Order# or
Invoice# and a negative Invoice Amount printed in trailing-minus notation
("7627.77-", matching extract_statement.py/Fred Beans' own convention for
negative amounts) - kept as a line item with those two fields blank.

Reconciliation: the printed "Total" row's Invoice Amount equals the sum of
every real transaction row's own Invoice Amount (Opening Balance and the
Total row itself excluded). Balance is NOT a running account total here -
on this statement it's identical to that same row's own Invoice Amount
(each invoice's own remaining balance, not yet discounted by anything) -
so it is not used for reconciliation, only carried through as its own
field.
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["Rivian, LLC"]

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")

FIELDNAMES = ["page", "doc_date", "order_number", "invoice_number", "invoice_amount",
              "due_date", "balance"]


def clean_money(raw):
    """'7627.77-' -> '-7627.77', '1409.1' -> '1409.1', '' -> ''."""
    s = (raw or "").strip().replace(",", "")
    if not s:
        return ""
    if s.endswith("-"):
        return f"-{s[:-1]}"
    return s


def parse_header_info(page1_text):
    info = {}
    m = re.search(r"Statement\s*#\s*:\s*(\S+)", page1_text)
    if m:
        info["statement_number"] = m.group(1)
    m = re.search(r"Date\s*:\s*(\S+)", page1_text)
    if m:
        info["statement_date"] = m.group(1)
        # This vendor prints the statement date "DD.MM.YYYY" (dot-separated,
        # day first - confirmed against Statement # "MMDDYYYY" printed
        # alongside it on this document: "09012026" / "01.09.2026" are the
        # same date, 2026-09-01). dateutil's day-first-ambiguous fallback in
        # adapter.py's _normalize_date() would otherwise misparse this as
        # month-first (2026-01-09) - so it's converted to unambiguous ISO
        # here instead, at the source, rather than trusting that guess.
        dm = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", m.group(1))
        if dm:
            day, month, year = dm.groups()
            info["statement_date_iso"] = f"{year}-{int(month):02d}-{int(day):02d}"
    m = re.search(r"Bill To\s*:\s*(.+)", page1_text)
    if m:
        info["bill_to"] = m.group(1).strip()
    m = re.search(r"Customer ID\s*:\s*(.+)", page1_text)
    if m:
        info["customer_id"] = m.group(1).strip()
    return info


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    line_items = []
    header_info = {}
    opening_balance = None
    total_printed = None

    with pdfplumber.open(pdf_path) as pdf:
        header_info = parse_header_info(pdf.pages[0].extract_text() or "")

        for page_num, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            if not tables:
                continue

            for table in tables:
                header = table[0]
                if not header or "Doc. Date" not in header:
                    continue

                for row in table[1:]:
                    # Row shape: [Doc. Date, Order#, Invoice#, Invoice
                    # Amount, <blank spacer>, Net Due Date, Balance]
                    doc_date, order_no, invoice_no, amount, _spacer, due_date, balance = (
                        (row + [None] * 7)[:7]
                    )
                    doc_date = (doc_date or "").strip()
                    label = (order_no or invoice_no or "").strip()

                    if doc_date == "Opening Balance" or label == "Opening Balance":
                        # This row's own value prints in the blank-spacer
                        # column position (index 4), not "Invoice Amount"
                        # (index 3, None here) - see this module's own
                        # docstring re: the unlabeled spacer column.
                        opening_balance = clean_money(amount or _spacer)
                        continue
                    if doc_date == "Total":
                        total_printed = clean_money(amount)
                        continue
                    if not DATE_RE.match(doc_date):
                        continue

                    line_items.append({
                        "page": page_num,
                        "doc_date": doc_date,
                        "order_number": (order_no or "").strip(),
                        "invoice_number": (invoice_no or "").strip(),
                        "invoice_amount": clean_money(amount),
                        "due_date": (due_date or "").strip(),
                        "balance": clean_money(balance),
                    })

    def to_float(s):
        return float(s) if s else 0.0

    computed_total = round(sum(to_float(r["invoice_amount"]) for r in line_items), 2)
    printed_total = to_float(total_printed)

    summary = dict(header_info)
    summary["opening_balance"] = opening_balance
    summary["total_printed"] = total_printed
    summary["total_computed"] = f"{computed_total:,.2f}"
    summary["reconciles"] = total_printed is not None and computed_total == printed_total

    return {
        "line_items": line_items,
        "fieldnames": FIELDNAMES,
        "summary": summary,
        "full_text": None,
    }


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "RIVEvolve0826.pdf"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
    for item in result["line_items"]:
        print(item)
