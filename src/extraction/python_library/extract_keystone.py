"""
Extract Keystone Automotive Industries (an LKQ company) monthly account
statement PDF into:
  1. Keystone Neet's - line items.csv  (structured per-invoice activity list)
  2. Keystone Neet's - summary.csv     (header info + printed totals)

This PDF has real embedded text (confirmed via pdfplumber probe - not a
scan). pdfplumber's find_tables()/extract_table() DOES detect a table on
each page, but it is a trap: because there are no ruled row separators,
extract_table() merges every row's cells for a given column into one
giant newline-joined string per column, collapsing all ~40 transactions
per page into a single pseudo-row. It also confirms (by which column
strings are non-empty) something important about this layout: line items
are reconstructed here from extract_words() using x0 column boundaries
measured directly from this document's header word positions, exactly
like extract_empire.py's approach.

Column quirk worth documenting: the printed header has 8 logical columns
(Reference Date, Reference Number, Purchase Order Number, Balance
Forward, Period Activity, Credit Applied, Payment Applied, Balance Due)
but every individual transaction row only ever prints 4 of the 5 numeric
values - NOT because "Balance Forward" is always blank (that was the
initial hypothesis, but checking actual word x-positions against the
header's x-ranges disproves it). What's actually going on, confirmed via
extract_words() x0/x1 vs. the header label positions:

  - Rows referencing invoices opened in a *prior* statement period carry
    a Balance Forward, and print Balance Forward / Credit Applied /
    Payment Applied / Balance Due (Period Activity is blank - there's no
    new charge this period, just settlement of the old one).
  - Rows for invoices opened *during* this statement period print only
    Period Activity / Balance Due (Balance Forward / Credit Applied /
    Payment Applied are blank - nothing carried in, nothing applied yet).

So "Balance Due" is the one column that is populated on every row and
already nets Balance Forward + Period Activity - Credit Applied -
Payment Applied into the actual amount currently owed for that specific
reference line. It is the correct column to sum for the statement total:
summing it across all 160 line items reproduces both the "Month Totals"
row's own Balance Due total and the "AMOUNT DUE: 10428.76" printed near
the top of page 1, to the cent.
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["Keystone Automotive Industries"]

ROW_TOLERANCE = 3.0

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")

# Column boundaries (x0), measured from this document's header word
# positions (e.g. "Balance Forward" header spans x0 260.6-317.0, "Period
# Activity" spans x0 329.0-378.0, etc.) with boundaries set at the
# midpoints between adjacent header columns.
COLUMN_BOUNDS = [
    ("reference_date", 0, 84.45),
    ("reference_number", 84.45, 152.3),
    ("purchase_order_number", 152.3, 244.2),
    ("balance_forward", 244.2, 323.0),
    ("period_activity", 323.0, 387.4),
    ("credit_applied", 387.4, 451.95),
    ("payment_applied", 451.95, 523.25),
    ("balance_due", 523.25, 10_000),
]

FIELDNAMES = [name for name, _, _ in COLUMN_BOUNDS]


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
    m = re.search(r"Statement Date:\s*(\d{2}/\d{2}/\d{2})", page1_text)
    if m:
        info["statement_date"] = m.group(1)
    m = re.search(r"Customer Terms:\s*(.+)", page1_text)
    if m:
        info["terms"] = m.group(1).strip()
    m = re.search(r"Location:\s*(\S+)", page1_text)
    if m:
        info["location"] = m.group(1)
    m = re.search(r"\n(\d{5,9})\n([A-Z][A-Za-z0-9 &.,'-]+?)\s+Remit To:\n", page1_text)
    if m:
        info["account_number"] = m.group(1)
        info["customer_name"] = m.group(2).strip()
    m = re.search(r"\n([^\n]*?)\s+Keystone Automotive Industries, Inc\.\n([^\n]+)\n", page1_text)
    if m:
        info["billing_address"] = m.group(1).strip()
        info["billing_city_state_zip"] = m.group(2).strip()
    return info


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    line_items = []
    header_info = {}
    amount_due_printed = None
    month_totals = None
    current_past_due_pay = None

    with pdfplumber.open(pdf_path) as pdf:
        page1_text = pdf.pages[0].extract_text() or ""
        header_info = parse_header_info(page1_text)
        m = re.search(r"AMOUNT DUE:\s*([\d,.\-]+)", page1_text)
        if m:
            amount_due_printed = m.group(1)

        for page_num, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""

            m = re.search(
                r"Month Totals\s+([\d,.\-]+)\s+([\d,.\-]+)\s+([\d,.\-]+)\s+([\d,.\-]+)\s+([\d,.\-]+)",
                page_text,
            )
            if m:
                month_totals = {
                    "balance_forward": m.group(1),
                    "period_activity": m.group(2),
                    "credit_applied": m.group(3),
                    "payment_applied": m.group(4),
                    "balance_due": m.group(5),
                }

            m = re.search(
                r"CURRENT PAST DUE PAY THIS AMOUNT\s*\n([\d,.\-]+)\s+([\d,.\-]+)\s+([\d,.\-]+)",
                page_text,
            )
            if m:
                current_past_due_pay = {
                    "current": m.group(1),
                    "past_due": m.group(2),
                    "pay_this_amount": m.group(3),
                }

            words = page.extract_words()
            rows = group_rows(words)

            for row in rows:
                cols = {name: [] for name in FIELDNAMES}
                for w in row:
                    col = bucket_column(w["x0"])
                    if col:
                        cols[col].append(w)

                # Dates/numbers are single tokens - join without spaces;
                # the PO number column can occasionally wrap so join with
                # a space defensively.
                reference_date = "".join(w["text"] for w in cols["reference_date"])
                if not DATE_RE.match(reference_date):
                    continue  # not a genuine transaction row (header/footer/totals line)

                reference_number = "".join(w["text"] for w in cols["reference_number"])
                purchase_order_number = " ".join(w["text"] for w in cols["purchase_order_number"])
                balance_forward = "".join(w["text"] for w in cols["balance_forward"])
                period_activity = "".join(w["text"] for w in cols["period_activity"])
                credit_applied = "".join(w["text"] for w in cols["credit_applied"])
                payment_applied = "".join(w["text"] for w in cols["payment_applied"])
                balance_due = "".join(w["text"] for w in cols["balance_due"])

                line_items.append({
                    "reference_date": reference_date,
                    "reference_number": reference_number,
                    "purchase_order_number": purchase_order_number,
                    "balance_forward": balance_forward,
                    "period_activity": period_activity,
                    "credit_applied": credit_applied,
                    "payment_applied": payment_applied,
                    "balance_due": balance_due,
                })

    def to_float(s):
        return float(s.replace(",", "")) if s else 0.0

    # Balance Due is the only column populated on every row, and it
    # already nets Balance Forward + Period Activity - Credit Applied -
    # Payment Applied into the actual amount currently owed on that
    # reference line, so it's the column to sum for the statement total
    # (verified against both the printed "Month Totals" row and the
    # "AMOUNT DUE" figure on page 1 - see module docstring).
    computed_total = round(sum(to_float(r["balance_due"]) for r in line_items), 2)
    printed_total = round(to_float(amount_due_printed or "0"), 2)

    summary = dict(header_info)
    summary["amount_due_printed"] = amount_due_printed
    summary["total_computed"] = f"{computed_total:,.2f}"
    summary["total_printed"] = f"{printed_total:,.2f}"
    summary["reconciles"] = computed_total == printed_total
    if month_totals:
        summary["month_totals_balance_forward"] = month_totals["balance_forward"]
        summary["month_totals_period_activity"] = month_totals["period_activity"]
        summary["month_totals_credit_applied"] = month_totals["credit_applied"]
        summary["month_totals_payment_applied"] = month_totals["payment_applied"]
        summary["month_totals_balance_due"] = month_totals["balance_due"]
    if current_past_due_pay:
        summary["current_amount"] = current_past_due_pay["current"]
        summary["past_due_amount"] = current_past_due_pay["past_due"]
        summary["pay_this_amount_printed"] = current_past_due_pay["pay_this_amount"]

    return {
        "line_items": line_items,
        "fieldnames": FIELDNAMES,
        "summary": summary,
        "full_text": None,
    }


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "Keystone Neet's.pdf"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
