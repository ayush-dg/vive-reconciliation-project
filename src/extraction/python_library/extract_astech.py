"""
Extract asTech (Repairify) monthly statement PDF into:
  1. Astech Owego - line items.csv  (structured outstanding-invoice list)
  2. Astech Owego - summary.csv     (header info + printed totals)

This PDF has real embedded text (confirmed via pdfplumber probe - not a
scan), and unlike the Fred Beans / KSI statements, pdfplumber's native
extract_table() parses this layout cleanly on every page, so no manual
word-position bucketing is needed here.
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["asTech", "Repairify"]

HEADER_ROW = ["Invoice Date", "Invoice #", "Work Order #", "RO #", "Outstanding Amount", "Due Date"]
FIELDNAMES = ["invoice_date", "invoice_no", "work_order_no", "ro_no", "outstanding_amount", "due_date"]
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
MONEY_RE = re.compile(r"\$?\s*[\d,]+\.\d{2}")
CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")


def _find_money_cell(row):
    """pdfplumber's extract_table() produces a different cell count for
    the "Total Outstanding"/"Total Unapplied" row depending on the
    document -- confirmed: Middletown has 3 cells with the amount at
    index 1, Bristol/Lees have 6 cells with the amount at index 2 (extra
    blank/merged cells before the trailing "USD"). A fixed index breaks
    on that variance. Since the row is already unambiguously identified
    by its label (row[0]) before this runs, scanning the remaining cells
    for a money-shaped value that isn't a 3-letter currency code is safe
    and tolerates any cell-count shape."""
    for cell in row[1:]:
        if not cell:
            continue
        cell = cell.strip()
        if CURRENCY_CODE_RE.match(cell):
            continue
        if MONEY_RE.search(cell):
            return cell
    return None


def parse_header_info(page1_text):
    info = {}
    m = re.search(r"Outstanding as of (\d{2}/\d{2}/\d{4})", page1_text)
    if m:
        info["statement_as_of"] = m.group(1)
    m = re.search(r"To:\s*\n(.+)\n(.+)\n(.+)\n(.+)\n(\d{5})", page1_text)
    if m:
        info["customer_name"] = m.group(1).strip()
        info["billing_address"] = m.group(2).strip()
        info["billing_city"] = m.group(3).strip()
        info["billing_state"] = m.group(4).strip()
        info["billing_zip"] = m.group(5).strip()
    return info


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    line_items = []
    header_info = {}
    total_outstanding = None
    total_unapplied = None

    with pdfplumber.open(pdf_path) as pdf:
        header_info = parse_header_info(pdf.pages[0].extract_text() or "")

        for page in pdf.pages:
            page_text = page.extract_text() or ""
            m = re.search(r"Total Unapplied Payment Amount:\s*\$\s*([\d,.\-]+)", page_text)
            if m:
                total_unapplied = m.group(1)

            table = page.extract_table()
            if not table:
                continue
            for row in table:
                if row == HEADER_ROW or all(not c for c in row):
                    continue
                if row[0] and "Total Outstanding" in row[0]:
                    total_outstanding = _find_money_cell(row)
                    continue
                if row[0] and "Total Unapplied" in row[0]:
                    total_unapplied = _find_money_cell(row)
                    continue
                if not DATE_RE.match(row[0] or ""):
                    continue
                line_items.append({
                    "invoice_date": row[0],
                    "invoice_no": row[1],
                    "work_order_no": row[2],
                    "ro_no": row[3],
                    "outstanding_amount": (row[4] or "").replace("$", "").strip(),
                    "due_date": row[5],
                })

    def to_float(s):
        # PDF text extraction sometimes splits a negative sign from its
        # digits with a space (e.g. "- 74.96", seen live on
        # outstanding_amount) -- float() rejects that outright, unlike a
        # plain "-74.96". Collapse that gap before parsing.
        if not s:
            return 0.0
        s = re.sub(r"^([+-])\s+", r"\1", s.replace("$", "").replace(",", "").strip())
        return float(s)

    computed_total = round(sum(to_float(r["outstanding_amount"]) for r in line_items), 2)
    printed_total = to_float(total_outstanding)

    summary = dict(header_info)
    summary["total_outstanding_invoices_printed"] = total_outstanding
    summary["total_outstanding_invoices_computed"] = f"{computed_total:,.2f}"
    summary["reconciles"] = computed_total == printed_total
    summary["total_unapplied_payment_amount"] = total_unapplied

    return {
        "line_items": line_items,
        "fieldnames": FIELDNAMES,
        "summary": summary,
        "full_text": None,
    }


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "Astech Owego.pdf"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
