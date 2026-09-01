#!/usr/bin/env python3
"""Session 9, Task 9.3 — Fred Beans Parts known-vendor deterministic
extractor. Reused from the reference implementation's
src/extraction/python_library/extract_statement.py
(vive-reconciliation-project-threshold-0.8-and-dupe-disable) — the
word-position row reconstruction and right-edge (x1) money-column
classifier are that module's actual, already-verified logic, unchanged.
Confirmed live (2026-09-01): Claude's generic vision prompt extracted 273
lines summing to $113,672.48 against a printed total of $23,986.36 — it
was conflating this layout's FOUR separate money columns (charges,
credits, amount_due, remit_amount_due — the last two being running-balance/
remittance-stub restatements, not new transaction amounts) into one
"amount" per row. This module's own column boundaries (measured directly
from the document, see the reference's docstring) resolve that
structurally rather than relying on a prompt to reverse-engineer it.

Same subprocess contract as scripts/extract_lia.py: `<script> <pdf_path>`,
one JSON object on stdout matching ExtractedStatement, non-zero exit +
{"error": ...} on failure. This project's single `amount` field (unlike the
reference's own separate charges/credits/amount_due/remit_amount_due
columns) is charges (positive) when populated, else -credits (negative)
when populated — never amount_due/remit_amount_due, which are the running
totals this whole port exists to stop treating as a line amount.
"""
import json
import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["Fred Beans Parts"]

ROW_TOLERANCE = 2.5  # px tolerance for grouping words into the same row

DATE_RE = re.compile(r"^\d{2}[A-Z]{3}\d{2}$")
CODE_RE = re.compile(r"^\d{2}$")
MONEY_RE = re.compile(r"^-?[\d,]+\.\d{2}-?$")

# Money column boundaries by right-edge (x1) — see the reference module's
# own docstring for exact measured values.
MONEY_COLUMNS = [
    ("charges", 320),
    ("credits", 400),
    ("amount_due", 500),
    ("remit_amount_due", 10_000),
]

_MONTH = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
    "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}


def classify_money(x1):
    for name, upper in MONEY_COLUMNS:
        if x1 <= upper:
            return name
    return "remit_amount_due"


def parse_money(s):
    if not s:
        return None
    s = s.strip()
    neg = s.endswith("-")
    if neg:
        s = s[:-1]
    s = s.replace(",", "")
    if not s:
        return None
    val = float(s)
    return -val if neg else val


def normalize_date(raw):
    if not raw:
        return None
    m = re.match(r"^(\d{2})([A-Z]{3})(\d{2})$", raw)
    if not m:
        return raw
    day, mon, yy = m.groups()
    month = _MONTH.get(mon)
    if not month:
        return raw
    return f"20{yy}-{month}-{day}"


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


def parse_header_info(page_text):
    info = {}
    m = re.search(r"(\d{2}[A-Z]{3}\d{2})\s+([A-Z0-9]+)\s+(\d+)\s*\n", page_text)
    if m:
        info["statement_date"] = m.group(1)
    return info


def parse_aging_summary(rows):
    """The aging totals row sits just below the 'CURRENT ... BALANCE DUE'
    label row. Grab the numeric row."""
    for i, row in enumerate(rows):
        texts = [w["text"] for w in row]
        joined = " ".join(texts)
        if joined.startswith("CURRENT") and "BALANCE DUE" in joined:
            for j in range(i + 1, min(i + 3, len(rows))):
                cand = rows[j]
                nums = [w["text"] for w in cand if MONEY_RE.match(w["text"])]
                if len(nums) >= 6:
                    return nums[-1]  # balance_due is the last of the aging totals
            break
    return None


def extract(pdf_path):
    """Returns {"line_items": [...], "summary": {...}}."""
    line_items = []
    header_info = {}
    balance_due_printed = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            plain_text = page.extract_text() or ""
            if page_num == 1:
                header_info = parse_header_info(plain_text)

            words = page.extract_words()
            rows = group_rows(words)

            for row in rows:
                row = sorted(row, key=lambda w: w["x0"])
                codes = [w for w in row if CODE_RE.match(w["text"])]
                dates = [w for w in row if DATE_RE.match(w["text"])]
                moneys = [w for w in row if MONEY_RE.match(w["text"])]
                others = [w for w in row if w not in codes and w not in dates and w not in moneys]

                if len(codes) != 2:
                    continue  # not a genuine line-item row

                date = dates[0]["text"] if dates else ""
                invoice_number = others[0]["text"] if len(others) >= 1 else ""

                money_cols = {"charges": "", "credits": "", "amount_due": "", "remit_amount_due": ""}
                for w in moneys:
                    money_cols[classify_money(w["x1"])] = w["text"]

                line_items.append({
                    "date": date,
                    "invoice_number": invoice_number,
                    "charges": money_cols["charges"],
                    "credits": money_cols["credits"],
                })

            if page_num == len(pdf.pages):
                balance_due_printed = parse_aging_summary(rows)

    last_date = None
    for item in line_items:
        if item["date"]:
            last_date = item["date"]
        else:
            item["date"] = last_date

    summary = dict(header_info)
    summary["balance_due_printed"] = balance_due_printed
    return {"line_items": line_items, "summary": summary}


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: extract_fred_beans.py <pdf_path>"}))
        return 1

    pdf_path = sys.argv[1]
    try:
        result = extract(pdf_path)
        summary = result["summary"]
        lines = []
        for item in result["line_items"]:
            charges = parse_money(item["charges"])
            credits = parse_money(item["credits"])
            amount = charges if charges is not None else (-abs(credits) if credits is not None else None)
            lines.append({
                "invoice_ref": item["invoice_number"] or None,
                "ro_number": None,
                "amount": amount,
                "date": normalize_date(item["date"]),
            })

        printed_total = parse_money(summary.get("balance_due_printed"))
        computed_total = round(sum(l["amount"] for l in lines if l["amount"] is not None), 2)
        statement = {
            "vendor_name_guess": "Fred Beans Parts, Inc.",
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
