#!/usr/bin/env python3
"""Session 9, Task 9.5 — Precision Diagnostics, Inc. known-vendor
deterministic extractor. Reused from the reference implementation's
src/extraction/python_library/extract_precision.py
(vive-reconciliation-project-threshold-0.8-and-dupe-disable) — Claude
already extracts this vendor's amounts correctly via the generic path
(27/27 matched in the reference project's own eval), so this port is for
cost/reliability, not correctness. Keeps this module's multi-line
transaction reconstruction (wrapped vehicle description/VIN/RO fragments
spread across several physical lines per transaction) unchanged.

Same subprocess contract as scripts/extract_lia.py: `<script> <pdf_path>`,
one JSON object on stdout matching ExtractedStatement, non-zero exit +
{"error": ...} on failure.
"""
import json
import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["Precision Diagnostics"]

ROW_TOLERANCE = 3.0

DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
INVOICE_NO_RE = re.compile(r"#INV(\d+)")

# Column boundaries (x0), measured from this document's word positions —
# see the reference module's own docstring for exact values.
COLUMN_BOUNDS = [
    ("date", 0, 100),
    ("description", 100, 270),
    ("charge", 380, 450),
    ("payment", 450, 520),
]


def bucket_column(x0):
    for name, lo, hi in COLUMN_BOUNDS:
        if lo <= x0 < hi:
            return name
    return "other"


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
    return (s or "").replace("$", "").strip()


def parse_money(s):
    s = clean_money(s)
    if not s:
        return 0.0
    return float(s.replace(",", ""))


def build_description(tokens):
    return " ".join(w["text"] for w in sorted(tokens, key=lambda w: w["x0"]))


def parse_header_info(page1_text):
    info = {}
    m = re.search(r"Statement\n(\d{1,2}/\d{1,2}/\d{4})", page1_text)
    if m:
        info["statement_date"] = m.group(1)
    m = re.search(r"Amount Due\n\$([\d,.\-]+)", page1_text)
    if m:
        info["amount_due_printed"] = m.group(1)
    return info


def new_transaction(cols):
    return {
        "date": " ".join(w["text"] for w in cols["date"]),
        "description_tokens": list(cols["description"]),
        "charge_tokens": list(cols["charge"]),
    }


def finalize_transaction(txn):
    description = build_description(txn["description_tokens"])
    m = INVOICE_NO_RE.search(description)
    return {
        "date": txn["date"],
        "invoice_no": m.group(1) if m else "",
        "description": description,
        "charge": clean_money(" ".join(w["text"] for w in txn["charge_tokens"])),
    }


def extract(pdf_path):
    """Returns {"line_items": [...], "summary": {...}}."""
    line_items = []
    header_info = {}

    with pdfplumber.open(pdf_path) as pdf:
        header_info = parse_header_info(pdf.pages[0].extract_text() or "")

        for page in pdf.pages:
            words = page.extract_words()
            rows = group_rows(words)

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
                    col = bucket_column(w["x0"])
                    if col in cols:
                        cols[col].append(w)

                date_text = " ".join(w["text"] for w in cols["date"])
                leading_x0 = min(w["x0"] for w in row)

                if DATE_RE.match(date_text):
                    if current_txn is not None:
                        finalized = finalize_transaction(current_txn)
                        if finalized["description"].strip().lower() != "balance forward":
                            line_items.append(finalized)
                    current_txn = new_transaction(cols)
                elif leading_x0 < 150:
                    break
                elif current_txn is not None:
                    current_txn["description_tokens"].extend(cols["description"])
                    current_txn["charge_tokens"].extend(cols["charge"])

            if current_txn is not None:
                finalized = finalize_transaction(current_txn)
                if finalized["description"].strip().lower() != "balance forward":
                    line_items.append(finalized)

    header_info["total_printed"] = header_info.get("amount_due_printed")
    return {"line_items": line_items, "summary": header_info}


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: extract_precision.py <pdf_path>"}))
        return 1

    pdf_path = sys.argv[1]
    try:
        result = extract(pdf_path)
        summary = result["summary"]
        lines = [
            {
                "invoice_ref": item["invoice_no"] or None,
                "ro_number": None,
                "amount": parse_money(item["charge"]) if item["charge"] else None,
                "date": item["date"] or None,
            }
            for item in result["line_items"]
        ]
        printed_total_str = summary.get("total_printed")
        printed_total = parse_money(printed_total_str) if printed_total_str else None
        computed_total = round(sum(l["amount"] for l in lines if l["amount"] is not None), 2)
        statement = {
            "vendor_name_guess": "Precision Diagnostics, Inc.",
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
