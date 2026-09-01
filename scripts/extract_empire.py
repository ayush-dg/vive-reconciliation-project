#!/usr/bin/env python3
"""Session 9, Task 9.4 — Empire Auto Parts known-vendor deterministic
extractor. Reused from the reference implementation's
src/extraction/python_library/extract_empire.py
(vive-reconciliation-project-threshold-0.8-and-dupe-disable) — the
column-bucketing logic (including the doc-number/description word-merge
fixup) is that module's actual, already-verified logic, unchanged. The
generic vendor-agnostic fallback scored 81.3% in the reference project's
own eval, consistently mis-splitting the merged "<description><doc#>"
token (e.g. "Highlander40444218") the same way this port explicitly
un-merges.

Same subprocess contract as scripts/extract_lia.py: `<script> <pdf_path>`,
one JSON object on stdout matching ExtractedStatement, non-zero exit +
{"error": ...} on failure.
"""
import json
import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["EMPIRE AUTO PARTS"]

ROW_TOLERANCE = 3.0

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
MONEY_RE = re.compile(r"^-?[\d,]+\.\d{2}$")
DOC_NO_RE = re.compile(r"^\d{7,9}$")

# Column boundaries (x0), measured from this document's word positions —
# see the reference module's own docstring for exact values.
COLUMN_BOUNDS = [
    ("transaction_date", 0, 65),
    ("description", 65, 200),
    ("doc_no", 200, 260),
    ("amount", 420, 470),
]


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


def extract(pdf_path):
    """Returns {"line_items": [...], "summary": {...}}."""
    line_items = []
    total_balance = None
    activity_through = None

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            full_text = page.extract_text() or ""
            m = re.search(r"Total Balance:\s*\$([\d,.\-]+)", full_text)
            if m:
                total_balance = m.group(1)
            m = re.search(r"Activity through (\d{2}/\d{2}/\d{2})", full_text)
            if m:
                activity_through = m.group(1)

            words = page.extract_words()
            rows = group_rows(words)

            for row in rows:
                cols = {name: [] for name, _, _ in COLUMN_BOUNDS}
                for w in row:
                    col = bucket_column(w["x0"])
                    if col:
                        cols[col].append(w)

                transaction_date = " ".join(w["text"] for w in cols["transaction_date"])
                desc_words = sorted(cols["description"], key=lambda w: w["x0"])
                description = " ".join(w["text"] for w in desc_words)
                doc_no = " ".join(w["text"] for w in cols["doc_no"])

                if not doc_no and desc_words:
                    m = re.search(r"(\d{7,9})$", desc_words[-1]["text"])
                    if m:
                        doc_no = m.group(1)

                amount = " ".join(w["text"] for w in cols["amount"])

                if DATE_RE.match(transaction_date) and DOC_NO_RE.match(doc_no):
                    line_items.append({"transaction_date": transaction_date, "doc_no": doc_no, "amount": amount})

    return {
        "line_items": line_items,
        "summary": {"activity_through": activity_through, "total_balance_printed": total_balance},
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: extract_empire.py <pdf_path>"}))
        return 1

    pdf_path = sys.argv[1]
    try:
        result = extract(pdf_path)
        summary = result["summary"]
        lines = [
            {
                "invoice_ref": item["doc_no"] or None,
                "ro_number": None,
                "amount": float(item["amount"].replace(",", "")) if MONEY_RE.match(item["amount"] or "") else None,
                "date": item["transaction_date"] or None,
            }
            for item in result["line_items"]
        ]
        printed_total_str = summary.get("total_balance_printed")
        printed_total = float(printed_total_str.replace(",", "")) if printed_total_str else None
        computed_total = round(sum(l["amount"] for l in lines if l["amount"] is not None), 2)
        statement = {
            "vendor_name_guess": "Empire Auto Parts",
            "statement_period": summary.get("activity_through"),
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
