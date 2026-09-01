#!/usr/bin/env python3
"""Session 9, Task 9.5 — asTech (Repairify) known-vendor deterministic
extractor. Reused from the reference implementation's
src/extraction/python_library/extract_astech.py
(vive-reconciliation-project-threshold-0.8-and-dupe-disable) — Claude
already extracts this vendor correctly via the generic path (106/106 lines,
confirmed 2026-09-01), so this port is for cost/reliability, not
correctness: pdfplumber's native table detection parses this layout
cleanly, so no word-position bucketing is needed here.

Same subprocess contract as scripts/extract_lia.py: `<script> <pdf_path>`,
one JSON object on stdout matching ExtractedStatement, non-zero exit +
{"error": ...} on failure.
"""
import json
import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["asTech", "Repairify"]

HEADER_ROW = ["Invoice Date", "Invoice #", "Work Order #", "RO #", "Outstanding Amount", "Due Date"]
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def parse_header_info(page1_text):
    info = {}
    m = re.search(r"Outstanding as of (\d{2}/\d{2}/\d{4})", page1_text)
    if m:
        info["statement_as_of"] = m.group(1)
    return info


def extract(pdf_path):
    """Returns {"line_items": [...], "summary": {...}}."""
    line_items = []
    total_outstanding = None

    with pdfplumber.open(pdf_path) as pdf:
        header_info = parse_header_info(pdf.pages[0].extract_text() or "")

        for page in pdf.pages:
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
                    continue
                if not DATE_RE.match(row[0] or ""):
                    continue
                line_items.append({
                    "invoice_date": row[0],
                    "invoice_no": row[1],
                    "outstanding_amount": (row[4] or "").replace("$", "").strip(),
                })

    header_info["total_printed"] = total_outstanding
    return {"line_items": line_items, "summary": header_info}


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: extract_astech.py <pdf_path>"}))
        return 1

    pdf_path = sys.argv[1]
    try:
        result = extract(pdf_path)
        summary = result["summary"]
        lines = [
            {
                "invoice_ref": item["invoice_no"] or None,
                "ro_number": None,
                "amount": float(item["outstanding_amount"].replace(",", "")) if item["outstanding_amount"] else None,
                "date": item["invoice_date"] or None,
            }
            for item in result["line_items"]
        ]
        printed_total_str = summary.get("total_printed")
        printed_total = float(printed_total_str.replace("$", "").replace(",", "")) if printed_total_str else None
        computed_total = round(sum(l["amount"] for l in lines if l["amount"] is not None), 2)
        statement = {
            "vendor_name_guess": "asTech (Repairify, Inc.)",
            "statement_period": summary.get("statement_as_of"),
            "statement_total": printed_total if printed_total is not None else computed_total,
            "lines": lines,
        }
        print(json.dumps(statement))
        return 0
    except Exception as exc:  # noqa: BLE001 — see pdfplumber_extract.py's own note
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
