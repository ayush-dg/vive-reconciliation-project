"""
Extract Precision Diagnostics, Inc. customer statement PDF into:
  1. <name> - line items.csv  (structured transaction/ledger list)
  2. <name> - summary.csv     (header info + aging summary + printed totals)

This PDF has real embedded text (confirmed via pdfplumber probe - not a
scan), but pdfplumber's native extract_table() finds nothing usable here
(no ruled table lines for it to detect), so - like extract_empire.py -
line items are reconstructed from extract_words() using x0 column
boundaries measured directly from this document's word positions
(date / description / message on statement / charge / payment / balance).

Structural quirk unique to this vendor: every transaction's "Message on
Statement" (vehicle description, VIN, RO number) wraps across multiple
physical lines below the date/description/charge/balance line, and the
order those fragments print in is inconsistent row to row (sometimes the
RO number shares the first line with the invoice number, sometimes it's
on its own line after the vehicle description). This module groups all
words between one date-led line and the next into a single logical
transaction record, bucketing every row (start row and continuation rows
alike) into columns by x0 range and concatenating the message-column
fragments in the order they appear on the page.
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["Precision Diagnostics"]

ROW_TOLERANCE = 3.0

DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
MONEY_RE = re.compile(r"^-?\$?[\d,]+\.\d{2}$")
INVOICE_PAY_RE = re.compile(r"^(#INV\d+)Pay$")
INVOICE_NO_RE = re.compile(r"#INV(\d+)")

# Column boundaries (x0), measured from this document's word positions.
# Header row words: Date@41  Description@113  Message@275/on@312/Statement@324
#                   Charge@399  Payment@463  Balance@540
COLUMN_BOUNDS = [
    ("date", 0, 100),
    ("description", 100, 270),
    ("message_on_statement", 270, 380),
    ("charge", 380, 450),
    ("payment", 450, 520),
    ("balance", 520, 10_000),
]


def bucket_column(x0):
    for name, lo, hi in COLUMN_BOUNDS:
        if lo <= x0 < hi:
            return name
    return "balance"


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


def clean_money(s):
    """Strip a leading $ sign, keep digits/commas/decimal/minus."""
    return (s or "").replace("$", "").strip()


def parse_money(s):
    s = clean_money(s)
    if not s:
        return 0.0
    return float(s.replace(",", ""))


def build_description(tokens):
    """Join description-column word tokens, splitting the glued
    '#INV160200Pay' token (no space before 'Pay' in the source PDF) back
    into '#INV160200 Pay' so the rendered text reads naturally."""
    parts = []
    for w in sorted(tokens, key=lambda w: w["x0"]):
        text = w["text"]
        m = INVOICE_PAY_RE.match(text)
        if m:
            parts.append(m.group(1))
            parts.append("Pay")
        else:
            parts.append(text)
    return " ".join(parts)


def build_message(tokens):
    """Join message-column tokens (possibly gathered across several
    wrapped physical lines) in on-page reading order (top, then x0)."""
    ordered = sorted(tokens, key=lambda w: (round(w["top"], 1), w["x0"]))
    return " ".join(w["text"] for w in ordered)


def parse_header_info(page1_text):
    info = {}
    m = re.search(r"Statement\n(\d{1,2}/\d{1,2}/\d{4})", page1_text)
    if m:
        info["statement_date"] = m.group(1)
    m = re.search(
        r"Billing Address\n(.+)\n(.+)\n(.+)\n(.+)\n",
        page1_text,
    )
    if m:
        info["customer_name"] = m.group(1).strip()
        info["billing_address"] = m.group(2).strip()
        info["billing_city_state_zip"] = m.group(3).strip()
        info["billing_country"] = m.group(4).strip()
    m = re.search(r"Amount Due\n\$([\d,.\-]+)", page1_text)
    if m:
        info["amount_due_printed"] = m.group(1)
    return info


def parse_vendor_and_aging(last_page_text):
    info = {}
    m = re.search(r"From:\s*(.+?)\s+Remittance Slip", last_page_text)
    if m:
        info["vendor_name"] = m.group(1).strip()
    m = re.search(
        r"Remittance Slip\nTo: .+\nTransaction Date Amount Due\n"
        r".+? (\d{1,2}/\d{1,2}/\d{4}) \$([\d,.\-]+)\n"
        r"(.+)\n(.+)\n(.+)\n([\d\-]+)",
        last_page_text,
    )
    if m:
        info["vendor_address"] = m.group(3).strip()
        info["vendor_city_state_zip"] = m.group(4).strip()
        info["vendor_country"] = m.group(5).strip()
        info["vendor_phone"] = m.group(6).strip()

    m = re.search(
        r"Current 1-30 Days 31-60 Days 61-90 Days Over 90 Days Amount Due\n"
        r"\$?([\d,.\-]+) \$?([\d,.\-]+) \$?([\d,.\-]+) \$?([\d,.\-]+) "
        r"\$?([\d,.\-]+) \$?([\d,.\-]+)",
        last_page_text,
    )
    if m:
        info["aging_current"] = m.group(1)
        info["aging_1_30_days"] = m.group(2)
        info["aging_31_60_days"] = m.group(3)
        info["aging_61_90_days"] = m.group(4)
        info["aging_over_90_days"] = m.group(5)
        info["aging_amount_due"] = m.group(6)
    return info


def new_transaction(page_num, cols):
    return {
        "page": page_num,
        "date": " ".join(w["text"] for w in cols["date"]),
        "description_tokens": list(cols["description"]),
        "message_tokens": list(cols["message_on_statement"]),
        "charge_tokens": list(cols["charge"]),
        "payment_tokens": list(cols["payment"]),
        "balance_tokens": list(cols["balance"]),
    }


def finalize_transaction(txn):
    return {
        "page": txn["page"],
        "date": txn["date"],
        "invoice_no": (
            INVOICE_NO_RE.search(build_description(txn["description_tokens"])).group(1)
            if INVOICE_NO_RE.search(build_description(txn["description_tokens"]))
            else ""
        ),
        "description": build_description(txn["description_tokens"]),
        "message_on_statement": build_message(txn["message_tokens"]),
        "charge": clean_money(" ".join(w["text"] for w in txn["charge_tokens"])),
        "payment": clean_money(" ".join(w["text"] for w in txn["payment_tokens"])),
        "balance": clean_money(" ".join(w["text"] for w in txn["balance_tokens"])),
    }


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    line_items = []
    opening_balance = None
    header_info = {}
    vendor_aging_info = {}

    with pdfplumber.open(pdf_path) as pdf:
        header_info = parse_header_info(pdf.pages[0].extract_text() or "")
        vendor_aging_info = parse_vendor_and_aging(pdf.pages[-1].extract_text() or "")

        for page_num, page in enumerate(pdf.pages, start=1):
            words = page.extract_words()
            rows = group_rows(words)

            # Skip everything up to and including the "Date Description
            # Message on Statement Charge Payment Balance" header row.
            started = False
            current_txn = None

            for row in rows:
                row_texts = {w["text"] for w in row}
                if not started:
                    if "Date" in row_texts and "Description" in row_texts:
                        started = True
                    continue

                cols = {name: [] for name, _, _ in COLUMN_BOUNDS}
                for w in row:
                    cols[bucket_column(w["x0"])].append(w)

                date_text = " ".join(w["text"] for w in cols["date"])
                leading_x0 = min(w["x0"] for w in row)

                if DATE_RE.match(date_text):
                    # New transaction row - flush whatever was being built.
                    if current_txn is not None:
                        finalized = finalize_transaction(current_txn)
                        if finalized["description"].strip().lower() == "balance forward":
                            opening_balance = finalized["balance"]
                        else:
                            line_items.append(finalized)
                    current_txn = new_transaction(page_num, cols)
                elif leading_x0 < 150:
                    # A row with no leading date but content starting near
                    # the left margin (e.g. "Notice: ...", the aging-summary
                    # "Current ..." row, the remittance-slip block) marks the
                    # end of the transaction table on this page.
                    break
                elif current_txn is not None:
                    # Continuation row: wrapped vehicle description / VIN /
                    # RO fragment belonging to the transaction above it.
                    current_txn["description_tokens"].extend(cols["description"])
                    current_txn["message_tokens"].extend(cols["message_on_statement"])
                    current_txn["charge_tokens"].extend(cols["charge"])
                    current_txn["payment_tokens"].extend(cols["payment"])
                    current_txn["balance_tokens"].extend(cols["balance"])
                # else: stray row before any transaction started - ignore.

            if current_txn is not None:
                finalized = finalize_transaction(current_txn)
                if finalized["description"].strip().lower() == "balance forward":
                    opening_balance = finalized["balance"]
                else:
                    line_items.append(finalized)
                current_txn = None

    fieldnames = ["page", "date", "invoice_no", "description",
                  "message_on_statement", "charge", "payment", "balance"]

    computed_total = round(sum(parse_money(r["charge"]) for r in line_items), 2)
    payments_found = any(r["payment"] for r in line_items)
    printed_total = parse_money(header_info.get("amount_due_printed"))
    last_balance = parse_money(line_items[-1]["balance"]) if line_items else 0.0
    aging_current = parse_money(vendor_aging_info.get("aging_current"))
    aging_amount_due = parse_money(vendor_aging_info.get("aging_amount_due"))

    reconciles = (
        abs(computed_total - printed_total) < 0.005
        and abs(computed_total - last_balance) < 0.005
        and abs(computed_total - aging_current) < 0.005
        and abs(computed_total - aging_amount_due) < 0.005
    )

    summary = dict(header_info)
    summary.update(vendor_aging_info)
    summary["opening_balance_forward"] = opening_balance
    summary["opening_balance_forward_note"] = (
        "The statement's first data row is 'Balance Forward $0.00'. It is "
        "excluded from line_items (it is not an actual charge/invoice, just "
        "the ledger's starting balance) and is reported here instead."
    )
    summary["payment_column_used"] = payments_found
    summary["payment_column_note"] = (
        "The header defines a 'Payment' column but no row in this statement "
        "has a value in it - every transaction is a Charge, so the running "
        "Balance is a pure additive sum of Charges."
        if not payments_found else
        "One or more rows had a non-empty Payment value."
    )
    summary["total_computed_from_charges"] = f"{computed_total:,.2f}"
    summary["total_computed"] = f"{computed_total:,.2f}"
    summary["total_printed"] = header_info.get("amount_due_printed")
    summary["last_row_balance"] = line_items[-1]["balance"] if line_items else None
    summary["reconciles"] = reconciles

    return {
        "line_items": line_items,
        "fieldnames": fieldnames,
        "summary": summary,
        "full_text": None,
    }


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "Precision Diagnostics Klapec.pdf"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
