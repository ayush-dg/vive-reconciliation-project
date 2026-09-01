#!/usr/bin/env python3
"""Session 9, Task 9.2 — Keystone Automotive Industries known-vendor
deterministic extractor. Reused from the reference implementation's
src/extraction/python_library/extract_keystone.py
(vive-reconciliation-project-threshold-0.8-and-dupe-disable) — the
column-bucketing logic and its column boundaries are that module's actual,
already-verified logic, unchanged. Claude's generic vision prompt scored 0%
on this vendor (every line's sign/value came back wrong) — this statement's
"Balance Due" column already nets Balance Forward + Period Activity -
Credit Applied - Payment Applied per row, and no generic prompt can be
expected to reverse-engineer that from a scan of the page; the reference
module's own docstring explains exactly why and how it verified this
against both the printed "Month Totals" row and the page-1 "AMOUNT DUE"
figure.

Same subprocess contract as scripts/extract_lia.py: `<script> <pdf_path>`,
one JSON object on stdout matching ExtractedStatement, non-zero exit +
{"error": ...} on failure.
"""
import json
import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["Keystone Automotive Industries"]

ROW_TOLERANCE = 3.0

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")

# Column boundaries (x0), measured from this document's header word
# positions — see the reference module's own docstring for exact values.
COLUMN_BOUNDS = [
    ("reference_date", 0, 84.45),
    ("reference_number", 84.45, 152.3),
    ("purchase_order_number", 152.3, 244.2),
    ("balance_forward", 244.2, 323.0),
    ("period_activity", 323.0, 387.4),
    ("credit_applied", 387.4, 451.95),
    ("payment_applied", 451.95, 523.25),
    ("balance_due", 523.25, 10_000),
]

FIELDNAMES = [name for name, _, _ in COLUMN_BOUNDS]


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


def parse_header_info(page1_text):
    info = {}
    m = re.search(r"Statement Date:\s*(\d{2}/\d{2}/\d{2})", page1_text)
    if m:
        info["statement_date"] = m.group(1)
    return info


def to_float(s):
    return float(s.replace(",", "")) if s else 0.0


def extract(pdf_path):
    """Returns {"line_items": [...], "summary": {...}} — the reference
    module's own shape, unchanged (adapted into this project's
    ExtractedStatement contract in main(), below, not here)."""
    line_items = []
    amount_due_printed = None

    with pdfplumber.open(pdf_path) as pdf:
        page1_text = pdf.pages[0].extract_text() or ""
        summary = parse_header_info(page1_text)
        m = re.search(r"AMOUNT DUE:\s*([\d,.\-]+)", page1_text)
        if m:
            amount_due_printed = m.group(1)

        for page in pdf.pages:
            words = page.extract_words()
            rows = group_rows(words)

            for row in rows:
                cols = {name: [] for name in FIELDNAMES}
                for w in row:
                    col = bucket_column(w["x0"])
                    if col:
                        cols[col].append(w)

                reference_date = "".join(w["text"] for w in cols["reference_date"])
                if not DATE_RE.match(reference_date):
                    continue  # not a genuine transaction row (header/footer/totals line)

                reference_number = "".join(w["text"] for w in cols["reference_number"])
                balance_due = "".join(w["text"] for w in cols["balance_due"])

                line_items.append({
                    "reference_date": reference_date,
                    "reference_number": reference_number,
                    "balance_due": balance_due,
                })

    computed_total = round(sum(to_float(r["balance_due"]) for r in line_items), 2)
    printed_total = round(to_float(amount_due_printed or "0"), 2)
    summary["total_computed"] = computed_total
    summary["total_printed"] = printed_total if amount_due_printed else None

    return {"line_items": line_items, "summary": summary}


def normalize_date(raw):
    """'07/31/26' -> '2026-07-31'."""
    m = re.match(r"^(\d{2})/(\d{2})/(\d{2})$", raw)
    if not m:
        return raw
    mm, dd, yy = m.groups()
    return f"20{yy}-{mm}-{dd}"


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: extract_keystone.py <pdf_path>"}))
        return 1

    pdf_path = sys.argv[1]
    try:
        result = extract(pdf_path)
        summary = result["summary"]
        lines = [
            {
                "invoice_ref": item["reference_number"] or None,
                "ro_number": None,
                "amount": to_float(item["balance_due"]),
                "date": normalize_date(item["reference_date"]),
            }
            for item in result["line_items"]
        ]
        printed_total = summary.get("total_printed")
        statement = {
            "vendor_name_guess": "Keystone Automotive Industries",
            "statement_period": summary.get("statement_date"),
            "statement_total": printed_total if printed_total is not None else summary.get("total_computed"),
            "lines": lines,
        }
        print(json.dumps(statement))
        return 0
    except Exception as exc:  # noqa: BLE001 — see pdfplumber_extract.py's own note
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
