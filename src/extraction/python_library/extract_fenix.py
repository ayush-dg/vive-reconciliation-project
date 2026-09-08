"""
Extract Fenix NE (auto-parts) customer account statement PDF into:
  1. <stem> - line items.csv  (structured transaction list)
  2. <stem> - summary.csv     (header info + printed Total due / Unallocated / Balance due)

This PDF has real embedded text (confirmed via pdfplumber probe - not a
scan). pdfplumber's native extract_tables() only finds the small
aging-bucket summary table (Open Items / Unalloc. Items / Aged Amount) at
the top of each page - the ledger body isn't ruled, so line items are
reconstructed from extract_words() using x-position bucketing, the same
technique used in extract_empire.py / extract_abc.py.

Each ledger row is one of three transaction types (identified by the first
word(s) of the "Transaction Type" column):
  - "Invoice #<num>"                       - a new charge
  - "Credit #<num> for inv."               - a credit against an earlier
    invoice, whose own number wraps to a second physical line directly
    beneath (e.g. "3336598") - folded into original_invoice_ref.
  - "Payment: Check <num>"                 - a lump-sum payment; the same
    "Payment: Check <num>" text is also mirrored a second time, far to the
    right on the SAME physical line, as a tear-off remittance stub (see
    extract_wilberts.py's own docstring for the same pattern on a
    different vendor) - that duplicate is intentionally ignored.

Four money columns exist per row, but the printed table is NOT ruled and
three of the four are right-aligned to fixed pixel boundaries (measured
directly from this document's word positions) while the fourth ("Due") is
left-aligned immediately before the Description text with no gap - so a
"Due" value and the start of Description are frequently rendered as one
merged pdfplumber word, e.g. "0.00(OCE)" or "1325.00(OCE)" (split back
apart here via regex). Bucketing therefore classifies each word by its
RIGHT edge (x1) for Charged/Paid/Unalloc., and by LEFT edge (x0) for the
Due+Description zone, rather than the single x0-bucket approach used for
vendors with simpler layouts:
  - Charged  (x1 ~324): the invoice's own original charge amount. Blank
    for Credit/Payment rows.
  - Paid     (x1 ~362): the credit amount (Credit rows) or the payment
    amount (Payment rows). Usually blank for Invoice rows.
  - Unalloc. (x1 ~400): running unallocated-payment-pool amount. Zero for
    ordinary Credit rows, populated on Payment rows.
  - Due      (x0 ~403-425, glued to Description): the invoice's own
    remaining open amount - zero if immediately offset by existing
    floating credit, otherwise usually equal to Charged. Blank for
    Credit/Payment rows (they don't carry their own "due").

Reconciliation (confirmed against this document): sum(Due) across every
row equals the statement's printed "Total due"; sum(Unalloc.) equals
"Unallocated"; Total due - Unallocated equals "Balance due".
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["Fenix NE"]

ROW_TOLERANCE = 3.0

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
MONEY_RE = re.compile(r"^-?[\d,]+\.\d{2}$")
# A due-value merged directly onto the start of Description with no space,
# e.g. "0.00(OCE)" or "1325.00(OCE)" - split amount from the rest.
DUE_MERGED_RE = re.compile(r"^(-?[\d,]+\.\d{2})(.*)$")
CONTINUATION_REF_RE = re.compile(r"^\d{5,9}$")

FIELDNAMES = ["page", "date", "type", "reference_number", "original_invoice_ref",
              "sls", "po_chk_number", "charged", "paid", "unalloc", "due", "description"]


def clean_money(raw):
    if not raw:
        return ""
    return raw.replace(",", "")


def classify(word):
    x0, x1 = word["x0"], word["x1"]
    if x0 < 45:
        return "date"
    if x0 < 172:
        return "transaction_type"
    if x0 < 221:
        return "sls"
    if x0 < 291:
        return "po_chk"
    if x1 <= 330:
        return "charged"
    if x1 <= 368:
        return "paid"
    if x1 <= 404 and x0 < 400:
        return "unalloc"
    return "due_desc"


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


def parse_header_info(page1_words, page1_text):
    rows = group_rows(page1_words)

    def row_text(row):
        return " ".join(w["text"] for w in sorted(row, key=lambda w: w["x0"]))

    info = {}
    vendor_rows = [r for r in rows if 45 <= r[0]["top"] <= 90 and r[0]["x0"] < 300]
    vendor_lines = [row_text(r) for r in vendor_rows]
    if len(vendor_lines) >= 3:
        info["vendor_name"] = vendor_lines[0]
        info["vendor_address"] = vendor_lines[1]
        info["vendor_city_state_zip"] = vendor_lines[2]

    m = re.search(r"Statement\s*#\s*(\d+)", page1_text)
    if m:
        info["statement_number"] = m.group(1)
    m = re.search(r"Period\s+(\d{2}/\d{2}/\d{2})\s*-\s*(\d{2}/\d{2}/\d{2})", page1_text)
    if m:
        info["period_start"] = m.group(1)
        info["period_end"] = m.group(2)

    customer_rows = [r for r in rows if 150 <= r[0]["top"] <= 180 and r[0]["x0"] < 300]
    customer_lines = [row_text(r) for r in customer_rows]
    if len(customer_lines) >= 3:
        info["customer_name"] = customer_lines[0]
        info["billing_address"] = customer_lines[1]
        info["billing_city_state_zip"] = customer_lines[2]

    return info


def parse_totals(last_page_text):
    info = {}
    m = re.search(r"Total due\s+([\d,]+\.\d{2})", last_page_text)
    if m:
        info["total_due_printed"] = m.group(1)
    m = re.search(r"Unallocated\s+([\d,]+\.\d{2})", last_page_text)
    if m:
        info["unallocated_printed"] = m.group(1)
    m = re.search(r"Balance due\s+([\d,]+\.\d{2})", last_page_text)
    if m:
        info["balance_due_printed"] = m.group(1)
    return info


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
                cols = {}
                for w in row:
                    cols.setdefault(classify(w), []).append(w)

                date = " ".join(w["text"] for w in cols.get("date", []))

                if DATE_RE.match(date):
                    tx_words = sorted(cols.get("transaction_type", []), key=lambda w: w["x0"])
                    tx_text = " ".join(w["text"] for w in tx_words)

                    if tx_text.startswith("Invoice"):
                        tx_type = "INVOICE"
                    elif tx_text.startswith("Credit"):
                        tx_type = "CREDIT"
                    elif tx_text.startswith("Payment"):
                        tx_type = "PAYMENT"
                    else:
                        tx_type = ""

                    if tx_type == "PAYMENT":
                        m = re.search(r"Check\s+(\S+)", tx_text)
                        reference_number = m.group(1) if m else ""
                    else:
                        m = re.search(r"#(\S+)", tx_text)
                        reference_number = m.group(1) if m else ""

                    due_desc_words = sorted(cols.get("due_desc", []), key=lambda w: w["x0"])
                    if tx_type == "PAYMENT":
                        # A Payment row's Description zone holds nothing but
                        # a second, far-right mirror of this same row's own
                        # "Payment: Check <num>" text - a tear-off
                        # remittance-stub duplicate (see extract_wilberts.py's
                        # own docstring for the same pattern), not real
                        # transaction data. Drop it rather than surfacing it
                        # as if it were a genuine description.
                        due_desc_words = []
                    due = ""
                    description_parts = []
                    if due_desc_words:
                        first = due_desc_words[0]["text"]
                        m = DUE_MERGED_RE.match(first)
                        if m:
                            due = clean_money(m.group(1))
                            if m.group(2):
                                description_parts.append(m.group(2))
                            due_desc_words = due_desc_words[1:]
                        description_parts.extend(w["text"] for w in due_desc_words)
                    description = " ".join(description_parts)

                    line_items.append({
                        "page": page_num,
                        "date": date,
                        "type": tx_type,
                        "reference_number": reference_number,
                        "original_invoice_ref": "",
                        "sls": " ".join(w["text"] for w in cols.get("sls", [])),
                        "po_chk_number": " ".join(w["text"] for w in cols.get("po_chk", [])),
                        "charged": clean_money(" ".join(w["text"] for w in cols.get("charged", []))),
                        "paid": clean_money(" ".join(w["text"] for w in cols.get("paid", []))),
                        "unalloc": clean_money(" ".join(w["text"] for w in cols.get("unalloc", []))),
                        "due": due,
                        "description": description,
                    })
                    continue

                # Continuation line: the wrapped original-invoice-number a
                # Credit row applies against - only the transaction_type
                # bucket populated, a bare 5-9 digit number, nothing else.
                tx_only = cols.get("transaction_type", [])
                other = [k for k in cols if k not in ("transaction_type",)]
                if tx_only and not other and line_items:
                    text = " ".join(w["text"] for w in tx_only)
                    if CONTINUATION_REF_RE.match(text):
                        line_items[-1]["original_invoice_ref"] = text

    totals = parse_totals(last_page_text)

    def to_float(s):
        return float(s) if s else 0.0

    computed_due_total = round(sum(to_float(r["due"]) for r in line_items), 2)
    computed_unalloc_total = round(sum(to_float(r["unalloc"]) for r in line_items), 2)
    printed_due = float(totals["total_due_printed"].replace(",", "")) if totals.get("total_due_printed") else None
    printed_unalloc = float(totals["unallocated_printed"].replace(",", "")) if totals.get("unallocated_printed") else None

    summary = dict(header_info)
    summary.update(totals)
    summary["total_due_computed"] = f"{computed_due_total:,.2f}"
    summary["unallocated_computed"] = f"{computed_unalloc_total:,.2f}"
    summary["reconciles"] = (
        printed_due is not None and computed_due_total == printed_due
        and printed_unalloc is not None and computed_unalloc_total == printed_unalloc
    )

    return {
        "line_items": line_items,
        "fieldnames": FIELDNAMES,
        "summary": summary,
        "full_text": None,
    }


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "FENCollex0826.pdf"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
    for item in result["line_items"]:
        print(item)
