"""
Extract a Parts Authority customer statement PDF into line items + summary.

Real embedded text, one fixed line shape (the vendor name itself is only in
the image letterhead):

    8/03/26 I 05970-PO-001 231.66 231.66 055568636 I 231.66
    8/14/26 C 055564244 196.48- 196.48- 055674379 C 196.48-
    8/27/26 C 117.72- 117.72- 055675494 C 117.72-
    8/05/26 I .00 055573253 I .00

  date, code (I invoice / C credit), an optional reference (the shop's PO,
  or for a credit the original invoice it reverses), the amount twice, the
  9-digit document number, the code again, and the amount (trailing '-' =
  negative).

Why this parser exists: through Claude the 9-digit document number -- the
only key NetSuite can match on -- was dropped on the one stored run (only
the PO reference came back), so matching had nothing to work with. In
NetSuite (entity 68562, confirmed 2026-10-06 on 58 lines) bills hold the
number with a dash after the 3-digit branch (055568636 -> 055-568636) and
credits without its leading zero (55674653); fabric_matching's
_alternate_tranids() retries both.

Zero-amount rows ('RETURN .00', a bare '.00') are placeholders, not
transactions, and are skipped. Reconciliation: the first amount on the line
after "Bouncers will be Redeposited" equals sum(amount).
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["Bouncers will be Redeposited"]

FIELDNAMES = ["page", "date", "code", "reference", "invoice_number", "amount"]

LINE_RE = re.compile(r"^(\d{1,2}/\d{2}/\d{2})\s+([IC])\s+(.*?)\s*(\d{9})\s+([IC])\s+([\d,]*\.\d{2}-?)$")
MONEY_RE = re.compile(r"^[\d,]*\.\d{2}-?$")
HEADER_RE = re.compile(r"^(.*?)\s+\d{5}\s+(\d{6})\s")


def clean_money(raw):
    """'196.48-' -> '-196.48'; '.00' -> '0.00'."""
    neg = raw.endswith("-")
    value = raw.rstrip("-").replace(",", "")
    value = f"{float(value):.2f}"
    return f"-{value}" if neg else value


def parse_line(line):
    m = LINE_RE.match(line.strip())
    if not m:
        return None
    date, code, middle, invoice_number, _, amount = m.groups()
    reference = " ".join(t for t in middle.split() if not MONEY_RE.match(t)) or None
    amount = clean_money(amount)
    if float(amount) == 0:
        return None
    return {"date": date, "code": code, "reference": reference, "invoice_number": invoice_number, "amount": amount}


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    line_items = []
    summary = {"statement_date": None, "customer_name": None, "account_no": None, "total_printed": None}
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            lines = (page.extract_text() or "").splitlines()
            if page_num == 1 and lines:
                summary["statement_date"] = lines[0].strip()
                m = HEADER_RE.match(lines[1]) if len(lines) > 1 else None
                if m:
                    summary["customer_name"], summary["account_no"] = m.group(1).strip(), m.group(2)
            for i, line in enumerate(lines):
                item = parse_line(line)
                if item:
                    item["page"] = page_num
                    line_items.append({k: item.get(k) for k in FIELDNAMES})
                if "Bouncers will be Redeposited" in line and i + 1 < len(lines):
                    first = lines[i + 1].split()
                    if first and MONEY_RE.match(first[0]):
                        summary["total_printed"] = clean_money(first[0])

    computed = round(sum(float(r["amount"]) for r in line_items), 2)
    summary["total_computed"] = f"{computed:.2f}"
    summary["reconciles"] = summary["total_printed"] is not None and round(float(summary["total_printed"]), 2) == computed
    return {"line_items": line_items, "fieldnames": FIELDNAMES, "summary": summary, "full_text": None}


if __name__ == "__main__":
    result = extract(sys.argv[1])
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
    for item in result["line_items"]:
        print(item)
