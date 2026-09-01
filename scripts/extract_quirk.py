#!/usr/bin/env python3
"""Session 9, Task 9.4 — Quirk Auto Group known-vendor deterministic
extractor. Reused from the reference implementation's
src/extraction/python_library/extract_quirk.py
(vive-reconciliation-project-threshold-0.8-and-dupe-disable) — the
watermark-filtering, column classification, and department-subtotal
detection are that module's actual, already-verified logic, unchanged.
The generic vendor-agnostic fallback scored only 82.8% on this vendor in
the reference project's own eval. This vendor's "amount" column is already
a single signed value (positive=charge, negative=credit/memo) — no
separate sign-flip step needed, unlike Fred Beans' split charges/credits
columns.

Same subprocess contract as scripts/extract_lia.py: `<script> <pdf_path>`,
one JSON object on stdout matching ExtractedStatement, non-zero exit +
{"error": ...} on failure.
"""
import json
import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["QUIRK AUTO GROUP"]

ROW_TOLERANCE = 3.0

DATE_RE = re.compile(r"^\d{2}-\d{2}$")
MONEY_RE = re.compile(r"^-?[\d,]+\.\d{2}$")
SUBTOTAL_CODE_RE = re.compile(r"^[A-Z]{0,2}\d{2,4}$")

WATERMARK_MAX_X1 = 28  # see the reference module's own docstring


def classify_word(w):
    text, x0, x1 = w["text"], w["x0"], w["x1"]
    if MONEY_RE.match(text):
        return "amount" if x1 <= 400 else "remit_balance"
    if x0 < 60:
        return "date"
    if x0 < 90:
        return "source"
    if x0 < 160:
        return "invoice"
    if x0 < 245:
        return "reference"
    if x0 < 360:
        return "description"
    return "other"


def drop_watermark(words):
    return [w for w in words if w["x0"] >= WATERMARK_MAX_X1]


def group_rows(words):
    rows = []
    current_top = None
    current_row = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if current_top is None or abs(w["top"] - current_top) <= ROW_TOLERANCE:
            current_row.append(w)
        else:
            rows.append(current_row)
            current_row = [w]
        current_top = w["top"]
    if current_row:
        rows.append(current_row)
    return rows


def parse_header_info(page1_text):
    info = {}
    m = re.search(r"\bDATE (\d{2} [A-Z]{3} \d{4}) (\d+)\b", page1_text)
    if m:
        info["statement_date"] = m.group(1)
    return info


def parse_grand_total(last_page_words):
    rows = group_rows(last_page_words)
    for i, row in enumerate(rows):
        texts = [w["text"] for w in row]
        if "NEW" in texts and "BALANCE" in texts:
            bal_word = next(w for w in row if w["text"] == "BALANCE")
            for j in range(i + 1, min(i + 3, len(rows))):
                for w in rows[j]:
                    if MONEY_RE.match(w["text"]) and abs(w["x0"] - bal_word["x0"]) < 40:
                        return w["text"]
    return None


def extract(pdf_path):
    """Returns {"line_items": [...], "summary": {...}}."""
    line_items = []
    header_info = {}
    printed_total = None

    with pdfplumber.open(pdf_path) as pdf:
        header_info = parse_header_info(pdf.pages[0].extract_text() or "")

        for page_num, page in enumerate(pdf.pages, start=1):
            words = drop_watermark(page.extract_words())
            rows = group_rows(words)

            for row in rows:
                cols = {"date": [], "invoice": [], "amount": [], "description": []}
                for w in row:
                    c = classify_word(w)
                    if c in cols:
                        cols[c].append(w)

                def joined(name):
                    return " ".join(w["text"] for w in sorted(cols[name], key=lambda w: w["x0"]))

                date = joined("date")
                invoice = joined("invoice")
                amount = joined("amount")

                if DATE_RE.match(date) and invoice:
                    line_items.append({"date": date, "invoice": invoice, "amount": amount})

            if page_num == len(pdf.pages):
                printed_total = parse_grand_total(words)

    header_info["total_printed"] = printed_total
    return {"line_items": line_items, "summary": header_info}


def normalize_date(raw, statement_date):
    """'07-07' + a statement_date like '31 JUL 2026' -> '2026-07-07' (borrows
    the statement's own year since the row's own date has no year)."""
    m = re.match(r"^(\d{2})-(\d{2})$", raw)
    if not m or not statement_date:
        return raw
    mm, dd = m.groups()
    ym = re.search(r"(\d{4})$", statement_date)
    return f"{ym.group(1)}-{mm}-{dd}" if ym else raw


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: extract_quirk.py <pdf_path>"}))
        return 1

    pdf_path = sys.argv[1]
    try:
        result = extract(pdf_path)
        summary = result["summary"]
        statement_date = summary.get("statement_date")
        lines = [
            {
                "invoice_ref": item["invoice"] or None,
                "ro_number": None,
                "amount": float(item["amount"].replace(",", "")) if item["amount"] else None,
                "date": normalize_date(item["date"], statement_date),
            }
            for item in result["line_items"]
        ]
        printed_total_str = summary.get("total_printed")
        printed_total = float(printed_total_str.replace(",", "")) if printed_total_str else None
        computed_total = round(sum(l["amount"] for l in lines if l["amount"] is not None), 2)
        statement = {
            "vendor_name_guess": "Quirk Auto Group",
            "statement_period": statement_date,
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
