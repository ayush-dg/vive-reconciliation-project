"""
Extract Adas Calibration Experts monthly statement PDF into:
  1. Adas Calibration Don Joe - line items.csv  (per-invoice rows)
  2. Adas Calibration Don Joe - summary.csv     (header info + aging buckets + totals)

This PDF has real embedded text (not a scan - no OCR needed) and a very
simple, clean layout: plain page.extract_text() already produces
well-formed single-line rows, so no OCR and no word-position bucketing
is needed here (unlike Fred Beans / KSI).

Every line-item row has the exact shape:
    DATE  Invoice #NNNNN: Due MM/DD/YYYY.  AMOUNT  OPEN_AMOUNT
which parses cleanly with a single regex per line. The "description"
field keeps the full "Invoice #NNNNN: Due MM/DD/YYYY." text verbatim
(matching the statement's own DESCRIPTION column), but the invoice
number and due date are also split out into invoice_no / due_date for
convenience.

Reconciliation note: AMOUNT is the original invoice amount; OPEN AMOUNT
is what's still unpaid. The statement's printed TOTAL DUE / Amount Due
($10,685.75) reconciles against the SUM OF THE OPEN AMOUNT column, not
the Amount column (older invoices are mostly paid off, so their open
amount is $0.00). The aging summary table (Current / 1-30 / 31-60 /
61-90 / 90+ / Amount Due) is a running total that prints identically
at the bottom of every page, so it's only parsed once (from the first
page that has it).
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["Adas Calibration Experts"]

HEADER_ROW = ["DATE", "DESCRIPTION", "AMOUNT", "OPEN AMOUNT"]
FIELDNAMES = ["date", "description", "amount", "open_amount", "invoice_no", "due_date"]

LINE_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+"
    r"(Invoice #(\d+): Due (\d{2}/\d{2}/\d{4})\.)\s+"
    r"([\d,]+\.\d{2})\s+"
    r"([\d,]+\.\d{2})$"
)

AGING_HEADER_RE = re.compile(
    r"Current 1-30 Days 31-60 Days 61-90 Days 90\+ Days Amount"
)
AGING_VALUES_RE = re.compile(
    r"([\d,]+\.\d{2}) ([\d,]+\.\d{2}) ([\d,]+\.\d{2}) ([\d,]+\.\d{2}) ([\d,]+\.\d{2}) \$([\d,]+\.\d{2})"
)


def _to_float(s):
    return float(s.replace(",", "").replace("$", "").strip())


def parse_header_info(page1_text):
    info = {}
    m = re.search(r"STATEMENT NO\.\s*(\S+)", page1_text)
    if m:
        info["statement_no"] = m.group(1)
    m = re.search(r"DATE\s+(\d{2}/\d{2}/\d{4})", page1_text)
    if m:
        info["statement_date"] = m.group(1)
    m = re.search(r"TOTAL DUE\s+\$([\d,]+\.\d{2})", page1_text)
    if m:
        info["total_due_printed"] = m.group(1)

    # Customer block sits between "TO" and "DATE" lines, e.g.:
    #   Don Joe Auto Body DATE 07/31/2026
    #   247 E Shore Rd TOTAL DUE $10,685.75
    #   Great Neck, NY 11023 US ENCLOSED
    m = re.search(
        r"^(.+?)\s+DATE\s+\d{2}/\d{2}/\d{4}\n"
        r"(.+?)\s+TOTAL DUE\s+\$[\d,]+\.\d{2}\n"
        r"(.+?)\s+US ENCLOSED",
        page1_text,
        re.MULTILINE,
    )
    if m:
        info["customer_name"] = m.group(1).strip()
        info["customer_address"] = m.group(2).strip()
        info["customer_city_state_zip"] = m.group(3).strip()

    return info


def parse_aging_summary(text):
    """Parses the Current/1-30/31-60/61-90/90+/Amount Due bucket table."""
    m = AGING_VALUES_RE.search(text)
    if not m:
        return {}
    return {
        "aging_current": m.group(1),
        "aging_1_30_days_past_due": m.group(2),
        "aging_31_60_days_past_due": m.group(3),
        "aging_61_90_days_past_due": m.group(4),
        "aging_90_plus_days_past_due": m.group(5),
        "aging_amount_due": m.group(6),
    }


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    line_items = []
    header_info = {}
    aging_info = {}

    with pdfplumber.open(pdf_path) as pdf:
        header_info = parse_header_info(pdf.pages[0].extract_text() or "")

        for page in pdf.pages:
            page_text = page.extract_text() or ""

            if not aging_info and AGING_HEADER_RE.search(page_text):
                aging_info = parse_aging_summary(page_text)

            for line in page_text.splitlines():
                m = LINE_RE.match(line.strip())
                if not m:
                    continue
                date, description, invoice_no, due_date, amount, open_amount = m.groups()
                line_items.append({
                    "date": date,
                    "description": description,
                    "amount": amount,
                    "open_amount": open_amount,
                    "invoice_no": invoice_no,
                    "due_date": due_date,
                })

    computed_total = round(sum(_to_float(r["open_amount"]) for r in line_items), 2)
    printed_total = _to_float(
        aging_info.get("aging_amount_due") or header_info.get("total_due_printed") or "0"
    )
    reconciles = computed_total == printed_total

    # Secondary cross-check: Current + 1-30 Days should also equal the total,
    # since 31-60 / 61-90 / 90+ are all 0.00 on this statement.
    aging_cross_check = None
    if aging_info:
        aging_cross_check = round(
            _to_float(aging_info["aging_current"]) + _to_float(aging_info["aging_1_30_days_past_due"]),
            2,
        )

    summary = dict(header_info)
    summary.update(aging_info)
    summary["total_computed"] = f"{computed_total:,.2f}"
    summary["total_printed"] = f"{printed_total:,.2f}"
    summary["reconciles"] = reconciles
    summary["aging_current_plus_1_30_cross_check"] = (
        f"{aging_cross_check:,.2f}" if aging_cross_check is not None else None
    )

    return {
        "line_items": line_items,
        "fieldnames": FIELDNAMES,
        "summary": summary,
        "full_text": None,
    }


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "Adas Calibration Don Joe.pdf"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
