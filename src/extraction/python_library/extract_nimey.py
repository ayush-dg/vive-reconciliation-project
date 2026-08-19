"""
Extract Matt Nimey GMC, Inc. (Boonville, NY) customer monthly statement PDF
into:
  1. <stem> - line items.csv  (structured invoice/payment transaction list)
  2. <stem> - summary.csv     (header info + printed totals)

This PDF has real embedded text (confirmed via pdfplumber probe - not a
scan), but pdfplumber's native extract_table() finds nothing usable here
(no ruled table lines for it to detect), so line items are reconstructed
from extract_words() using x0 column boundaries measured directly from
this document's word positions (# / invoice date / invoice # /
purchases-or-payments amount / balance).

Column quirk: the statement's header row reads "# Invoice Date Invoice#
Purchases Payments Balance", implying two separate amount columns, but in
practice every row's single dollar amount - whether a positive purchase
charge or a negative payment/credit - is rendered at the same x0 position
(the "Purchases" header's x-range); the "Payments" header's own x-range is
never populated. So there is really only one amount column per row, split
back into "purchases" / "payments" here by sign to match the printed
header names.

Row-10/11 quirk (invoice 1009236R): the printed table has 32 numbered
rows total across both pages, matching the "Invoices: 32" header count
exactly, and each numbered row is its own line item - not a header-plus-
wrapped-continuation. Two of those rows (10 and 11) happen to share the
same invoice number, 1009236R, each with its own dated amount
(-$125.00 and -$31.12), but only row 10 has a value in the Balance
position (-$156.12). -125.00 + -31.12 == -156.12 exactly, so row 10's
printed balance is the combined running balance for that invoice after
both of its transactions post, printed once against the first of the two
rows; row 11 has no balance of its own printed anywhere in the PDF. Both
rows are kept as separate line items (so the extracted row count is 32,
matching the document's own count), row 11's balance is left blank to
reflect what's actually printed, and a `note` field on both rows explains
the relationship. Summing the raw per-row amount (not the balance column,
which is blank for row 11) across all 32 rows reconciles exactly to the
printed total.
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["Matt Nimey GMC"]

ROW_TOLERANCE = 3.0

ROW_NO_RE = re.compile(r"^\d{1,2}$")
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
MONEY_RE = re.compile(r"^-?\$[\d,]+\.\d{2}$")

# Column boundaries (x0), measured from this document's word positions.
# Purchases and Payments share one physical x-position in this layout (see
# module docstring), so both are bucketed together as "amount" here and
# split apart by sign afterward.
COLUMN_BOUNDS = [
    ("row_no", 0, 60),
    ("invoice_date", 60, 155),
    ("invoice_no", 155, 330),
    ("amount", 330, 480),
    ("balance", 480, 10_000),
]

FIELDNAMES = ["row_no", "invoice_date", "invoice_no", "purchases", "payments", "balance", "note"]


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


def parse_money(text):
    if not text or not MONEY_RE.match(text):
        return None
    return float(text.replace("$", "").replace(",", ""))


def parse_header_info(page1_text):
    info = {}
    m = re.search(r"^(.+)\n(.+), NY (\d{5}) Monthly Statement", page1_text)
    if m:
        info["vendor_address_line1"] = m.group(1).strip()
        info["vendor_city_state_zip"] = f"{m.group(2).strip()}, NY {m.group(3).strip()}"
    m = re.search(r"Phone:\s*(.+?)\s+Customer Number:\s*(\d+)", page1_text)
    if m:
        info["vendor_phone"] = m.group(1).strip()
        info["customer_number"] = m.group(2).strip()
    m = re.search(r"Email:\s*(\S+)\s+Period:\s*(\d{2}/\d{2}/\d{2})\s*-\s*(\d{2}/\d{2}/\d{2})", page1_text)
    if m:
        info["vendor_email"] = m.group(1).strip()
        info["statement_period_start"] = m.group(2)
        info["statement_period_end"] = m.group(3)
    m = re.search(r"Due Date\s+(\d{2}/\d{2}/\d{2})", page1_text)
    if m:
        info["due_date"] = m.group(1)
    m = re.search(r"Total Amount Due\s+\$([\d,.\-]+)", page1_text)
    if m:
        info["total_amount_due_printed"] = m.group(1)
    m = re.search(r"\n([A-Z0-9 ,.'&-]+)\n(.+?) Make checks payable to (.+?)\n(.+?)\n", page1_text)
    if m:
        info["customer_name"] = m.group(1).strip()
        info["billing_address"] = m.group(2).strip()
        info["vendor_name"] = m.group(3).strip()
        info["billing_city_state_zip"] = m.group(4).strip()
    m = re.search(r"Invoices:\s*(\d+)\s+Amount Due:\s*\$([\d,.\-]+)", page1_text)
    if m:
        info["invoices_count_printed"] = m.group(1)
        info["amount_due_printed"] = m.group(2)
    return info


def parse_aging_info(all_text):
    info = {}
    m = re.search(
        r"Age Of Outstanding Balance\s*\n"
        r"Current 31-60 Days 61-90 Days 91-120 Days 120\+ Days\s*\n"
        r"\$([\d,.\-]+) \$([\d,.\-]+) \$([\d,.\-]+) \$([\d,.\-]+) \$([\d,.\-]+)",
        all_text,
    )
    if m:
        info["aging_current"] = m.group(1)
        info["aging_31_60_days"] = m.group(2)
        info["aging_61_90_days"] = m.group(3)
        info["aging_91_120_days"] = m.group(4)
        info["aging_120_plus_days"] = m.group(5)
    return info


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    line_items = []
    all_text_parts = []

    with pdfplumber.open(pdf_path) as pdf:
        page0_text = pdf.pages[0].extract_text() or ""
        header_info = parse_header_info(page0_text)

        for page in pdf.pages:
            page_text = page.extract_text() or ""
            all_text_parts.append(page_text)

            words = page.extract_words()
            rows = group_rows(words)

            for row in rows:
                cols = {name: [] for name, _, _ in COLUMN_BOUNDS}
                for w in row:
                    col = bucket_column(w["x0"])
                    if col:
                        cols[col].append(w)

                row_no = " ".join(w["text"] for w in cols["row_no"])
                invoice_date = " ".join(w["text"] for w in cols["invoice_date"])
                invoice_no = " ".join(w["text"] for w in cols["invoice_no"])
                amount_text = " ".join(w["text"] for w in sorted(cols["amount"], key=lambda w: w["x0"]))
                balance_text = " ".join(w["text"] for w in sorted(cols["balance"], key=lambda w: w["x0"]))

                # A genuine transaction row has a numbered row id and a dated invoice date.
                if not (ROW_NO_RE.match(row_no) and DATE_RE.match(invoice_date)):
                    continue

                amount_val = parse_money(amount_text)

                purchases = amount_text if (amount_val is not None and amount_val >= 0) else ""
                payments = amount_text if (amount_val is not None and amount_val < 0) else ""

                line_items.append({
                    "row_no": row_no,
                    "invoice_date": invoice_date,
                    "invoice_no": invoice_no,
                    "purchases": purchases,
                    "payments": payments,
                    "balance": balance_text,
                    "note": "",
                    "_amount_val": amount_val,
                })

    # Row-10/11 quirk: same invoice number on two consecutive rows, and the
    # second one has no balance of its own printed - annotate both rows
    # rather than silently dropping or merging either one (see module
    # docstring for the reconciliation math behind this).
    for i, item in enumerate(line_items):
        if item["balance"] == "" and i > 0:
            prev = line_items[i - 1]
            if prev["invoice_no"] == item["invoice_no"]:
                item["note"] = (
                    f"Continuation of invoice {item['invoice_no']} from row {prev['row_no']}; "
                    f"that row's balance ({prev['balance']}) is the combined total for both rows."
                )
                prev["note"] = (
                    f"Balance combines this row with row {item['row_no']} "
                    f"(same invoice {item['invoice_no']})."
                )

    computed_total = round(
        sum(item["_amount_val"] for item in line_items if item["_amount_val"] is not None), 2
    )
    for item in line_items:
        del item["_amount_val"]

    printed_total_str = header_info.get("total_amount_due_printed")
    printed_total = float((printed_total_str or "0").replace(",", ""))

    aging_info = parse_aging_info("\n".join(all_text_parts))

    summary = dict(header_info)
    summary.update(aging_info)
    summary["total_computed"] = f"{computed_total:,.2f}"
    summary["total_printed"] = printed_total_str
    summary["reconciles"] = computed_total == round(printed_total, 2)

    return {
        "line_items": line_items,
        "fieldnames": FIELDNAMES,
        "summary": summary,
        "full_text": None,
    }


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "Matt Nimey Sprague's.pdf"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
