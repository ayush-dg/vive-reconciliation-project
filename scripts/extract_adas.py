#!/usr/bin/env python3
"""Session 9, Task 9.4 — Adas Calibration Experts known-vendor deterministic
extractor. Reused from the reference implementation's
src/extraction/python_library/extract_adas.py
(vive-reconciliation-project-threshold-0.8-and-dupe-disable) — the per-line
regex and the "sum OPEN AMOUNT, not AMOUNT" reconciliation rule are that
module's actual, already-verified logic, unchanged. This is exactly the
trap the reference project's own adapter.py flags by name: AMOUNT is the
original invoice amount, OPEN AMOUNT is what's still unpaid — an older,
already-paid invoice shows a real non-zero AMOUNT but a correct $0.00 OPEN
AMOUNT, and reading AMOUNT instead silently overstates every closed
invoice. The generic fallback scored 87.5% in the reference project's own
eval with exactly this AMOUNT-vs-OPEN-AMOUNT confusion on every mismatch.

Same subprocess contract as scripts/extract_lia.py: `<script> <pdf_path>`,
one JSON object on stdout matching ExtractedStatement, non-zero exit +
{"error": ...} on failure.
"""
import json
import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["Adas Calibration Experts"]

LINE_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+"
    r"Invoice #(\d+): Due (\d{2}/\d{2}/\d{4})\.\s+"
    r"([\d,]+\.\d{2})\s+"
    r"([\d,]+\.\d{2})$"
)

AGING_VALUES_RE = re.compile(
    r"([\d,]+\.\d{2}) ([\d,]+\.\d{2}) ([\d,]+\.\d{2}) ([\d,]+\.\d{2}) ([\d,]+\.\d{2}) \$([\d,]+\.\d{2})"
)


def _to_float(s):
    return float(s.replace(",", "").replace("$", "").strip())


def parse_header_info(page1_text):
    info = {}
    m = re.search(r"DATE\s+(\d{2}/\d{2}/\d{4})", page1_text)
    if m:
        info["statement_date"] = m.group(1)
    m = re.search(r"TOTAL DUE\s+\$([\d,]+\.\d{2})", page1_text)
    if m:
        info["total_due_printed"] = m.group(1)
    return info


def extract(pdf_path):
    """Returns {"line_items": [...], "summary": {...}}."""
    line_items = []
    header_info = {}
    aging_amount_due = None

    with pdfplumber.open(pdf_path) as pdf:
        header_info = parse_header_info(pdf.pages[0].extract_text() or "")

        for page in pdf.pages:
            page_text = page.extract_text() or ""

            if aging_amount_due is None:
                m = AGING_VALUES_RE.search(page_text)
                if m:
                    aging_amount_due = m.group(6)

            for line in page_text.splitlines():
                m = LINE_RE.match(line.strip())
                if not m:
                    continue
                date, invoice_no, due_date, amount, open_amount = m.groups()
                line_items.append({"date": date, "invoice_no": invoice_no, "open_amount": open_amount})

    summary = dict(header_info)
    summary["total_printed"] = aging_amount_due or header_info.get("total_due_printed")
    return {"line_items": line_items, "summary": summary}


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: extract_adas.py <pdf_path>"}))
        return 1

    pdf_path = sys.argv[1]
    try:
        result = extract(pdf_path)
        summary = result["summary"]
        lines = [
            {
                "invoice_ref": item["invoice_no"] or None,
                "ro_number": None,
                "amount": _to_float(item["open_amount"]) if item["open_amount"] else None,
                "date": item["date"] or None,
            }
            for item in result["line_items"]
        ]
        printed_total_str = summary.get("total_printed")
        printed_total = _to_float(printed_total_str) if printed_total_str else None
        computed_total = round(sum(l["amount"] for l in lines if l["amount"] is not None), 2)
        statement = {
            "vendor_name_guess": "Adas Calibration Experts",
            "statement_period": summary.get("statement_date"),
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
