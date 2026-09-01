#!/usr/bin/env python3
"""Session 9, Task 9.4 — Wilbert's Inc. known-vendor deterministic
extractor. Reused from the reference implementation's
src/extraction/python_library/extract_wilberts.py
(vive-reconciliation-project-threshold-0.8-and-dupe-disable) — the
column-bucketing logic, DT# continuation-row merge, and the "sum Balance,
not Amount" reconciliation rule are that module's actual, already-verified
logic, unchanged. The generic vendor-agnostic fallback scored only 64% on
this vendor in the reference project's own eval (missing every credit-memo
row, since Amount and Balance disagree on the sole lump-sum Payment row —
see the reference module's own docstring for the exact mechanics).

Same subprocess contract as scripts/extract_lia.py: `<script> <pdf_path>`,
one JSON object on stdout matching ExtractedStatement, non-zero exit +
{"error": ...} on failure.
"""
import json
import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["Wilbert's Inc"]

ROW_TOLERANCE = 3.0

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
MONEY_RE = re.compile(r"^\(?\$[\d,]+\.\d{2}\)?$")
DT_CONTINUATION_RE = re.compile(r"^DT#\d+$")

# Column boundaries (x0), measured from this document's word positions —
# see the reference module's own docstring for exact values. Columns
# beyond x0=460 are a duplicate remittance-stub and are intentionally
# ignored.
COLUMN_BOUNDS = [
    ("date", 0, 85),
    ("invoice_number", 100, 156),
    ("reference", 156, 285),
    ("balance", 395, 460),
]


def bucket_column(x0):
    for name, lo, hi in COLUMN_BOUNDS:
        if lo <= x0 < hi:
            return name
    return None


def group_rows(words):
    rows = []
    current_top = None
    current_row = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if current_top is None or abs(w["top"] - current_top) <= ROW_TOLERANCE:
            current_row.append(w)
            current_top = w["top"] if current_top is None else current_top
        else:
            rows.append(current_row)
            current_row = [w]
            current_top = w["top"]
    if current_row:
        rows.append(current_row)
    return rows


def clean_money(raw):
    """'$320.20' -> '320.20', '($320.20)' -> '-320.20'."""
    s = raw.strip()
    if not s:
        return ""
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").replace(",", "")
    return f"-{s}" if neg else s


def parse_printed_total(last_page_text):
    m = re.search(r"Balance Due\s*\n\$([\d,]+\.\d{2})", last_page_text)
    return m.group(1) if m else None


def parse_statement_date(page1_text):
    m = re.search(r"Statement Date Account No\.\s*\n(\d{2}/\d{2}/\d{2})\s+(\d+)", page1_text)
    return m.group(1) if m else None


def extract(pdf_path):
    """Returns {"line_items": [...], "summary": {...}}."""
    line_items = []
    last_page_text = ""
    statement_date = None

    with pdfplumber.open(pdf_path) as pdf:
        statement_date = parse_statement_date(pdf.pages[0].extract_text() or "")

        for page in pdf.pages:
            last_page_text = page.extract_text() or ""
            words = page.extract_words()
            rows = group_rows(words)

            for row in rows:
                cols = {name: [] for name, _, _ in COLUMN_BOUNDS}
                for w in row:
                    col = bucket_column(w["x0"])
                    if col:
                        cols[col].append(w)

                date = " ".join(w["text"] for w in cols["date"])
                invoice_number = " ".join(w["text"] for w in sorted(cols["invoice_number"], key=lambda w: w["x0"]))
                reference = " ".join(w["text"] for w in sorted(cols["reference"], key=lambda w: w["x0"]))
                balance = " ".join(w["text"] for w in cols["balance"])
                # Amount column not bucketed here — see module docstring:
                # this port only needs `balance` (the correct per-row
                # reconciling value), not `amount` (double-counts the
                # lump-sum Payment row).
                amount_present = any(MONEY_RE.match(w["text"]) for w in row if 285 <= w["x0"] < 335)

                if DATE_RE.match(date) and amount_present:
                    line_items.append({
                        "date": date,
                        "invoice_number": invoice_number,
                        "reference": reference,
                        "balance": clean_money(balance),
                    })
                elif DT_CONTINUATION_RE.match(reference.strip()) and line_items:
                    line_items[-1]["reference"] += " " + reference.strip()

    printed_total_str = parse_printed_total(last_page_text)
    return {
        "line_items": line_items,
        "summary": {"statement_date": statement_date, "total_printed": printed_total_str},
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: extract_wilberts.py <pdf_path>"}))
        return 1

    pdf_path = sys.argv[1]
    try:
        result = extract(pdf_path)
        summary = result["summary"]
        lines = [
            {
                "invoice_ref": item["invoice_number"] or None,
                "ro_number": None,
                "amount": float(item["balance"]) if item["balance"] else None,
                "date": item["date"] or None,
            }
            for item in result["line_items"]
        ]
        printed_total_str = summary.get("total_printed")
        printed_total = float(printed_total_str.replace(",", "")) if printed_total_str else None
        computed_total = round(sum(l["amount"] for l in lines if l["amount"] is not None), 2)
        statement = {
            "vendor_name_guess": "Wilbert's Inc.",
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
