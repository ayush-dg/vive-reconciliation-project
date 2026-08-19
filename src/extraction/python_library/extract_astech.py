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
                    total_outstanding = row[2]
                    continue
                if row[0] and "Total Unapplied" in row[0]:
                    total_unapplied = row[2] if len(row) > 2 else None
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

    computed_total = round(sum(float(r["outstanding_amount"].replace(",", "")) for r in line_items), 2)
    printed_total = float((total_outstanding or "0").replace("$", "").replace(",", "").strip())

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
