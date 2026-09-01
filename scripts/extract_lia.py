#!/usr/bin/env python3
"""Session 8, Task 8.1 — Lia Auto Group known-vendor deterministic extractor.
Reused from the reference implementation's
src/extraction/python_library/extract_lia.py
(vive-reconciliation-project-threshold-0.8-and-dupe-disable) — the extract()
function, VENDOR_SIGNATURE, and every parsing helper below are that module's
actual logic, unchanged, since a real Lia Auto Group statement (confirmed via
that repo's own pdfplumber probe) needs the real word-position/right-edge
column reconstruction it already solved, not a reimplementation.

Adapted only at the boundary: the reference's own `if __name__ == "__main__"`
block (a human-readable summary print, meant for its own repo's manual
testing) is replaced below with this project's actual subprocess contract —
same shape as scripts/pdfplumber_extract.py and
scripts/pdfplumber_ocr_fallback.py: `<script> <pdf_path>`, one JSON object on
stdout matching ExtractedStatement (vendor_name_guess/statement_period/
statement_total/lines[] with invoice_ref/ro_number/amount/date), non-zero
exit + {"error": ...} on failure. The reference's own multi-field summary
(charges/credits/amount_due/aging buckets, etc.) has no equivalent column in
this project's silver.statement_line — only the single signed per-row
"balance" value is carried through as this project's `amount`, which the
reference's own module docstring already establishes as the correct
single-number reading for this vendor's layout (a purchase's balance is
positive, a credit memo's is the negative of its payments_credits value) —
no separate charge/credit split needed here, unlike adapter.py's general
multi-vendor _FIELD_MAP (this build wires only this one vendor, per
EXECUTION_PLAN.md Task 8.1's own scope).
"""
import json
import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["LIA AUTO GROUP", "Lia Group Payables"]

ROW_TOLERANCE = 2.5  # px tolerance for grouping words into the same row

DATE_RE = re.compile(r"^\d{2}[A-Z]{3}\d{2}$")
MONEY_RE = re.compile(r"^-?[\d,]+\.\d{2}-?$")

MONEY_COLUMNS = [
    ("purchases", 390),
    ("payments_credits", 470),
    ("balance", 10_000),
]

_MONTH = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
    "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}


def classify_money(x1):
    for name, upper in MONEY_COLUMNS:
        if x1 <= upper:
            return name
    return "balance"


def parse_money(s):
    """Parse a printed amount, handling this statement's trailing-minus
    convention for negatives (e.g. "50.00-" -> -50.00)."""
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
    """'23DEC25' -> '2025-12-23'. Returns the raw string unchanged if it
    doesn't match the expected DDMonYY shape."""
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
    """Group words into rows by their 'top' coordinate, anchored to the
    first word's top."""
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


def parse_header_info(page1_text):
    info = {}
    m = re.search(r"ACCT\.\s*NO\s*\n(\S+)", page1_text)
    if m:
        info["account_no"] = m.group(1).strip()
    m = re.search(r"CLOSING DATE\s*\n(.+?)\s+(\d{2}[A-Z]{3}\d{2})\n(.+)\n(.+)", page1_text)
    if m:
        info["customer_name"] = m.group(1).strip()
        info["closing_date"] = m.group(2).strip()
        info["billing_address"] = m.group(3).strip()
        info["billing_city_state_zip"] = m.group(4).strip()
    return info


def parse_aging_summary(words):
    """The aging totals only print on the last page. Locate the "PAST DUE /
    CURRENT / ... PLEASE PAY" label row and pull the money tokens out of the
    row immediately following it."""
    rows = group_rows(words)
    aging = {}

    for i, row in enumerate(rows):
        texts = [w["text"] for w in row]
        if "PAST" in texts and "DUE" in texts and "CURRENT" in texts:
            for j in range(i + 1, min(i + 3, len(rows))):
                moneys = sorted((w for w in rows[j] if MONEY_RE.match(w["text"])), key=lambda w: w["x0"])
                if len(moneys) >= 3:
                    aging["past_due"] = moneys[0]["text"]
                    aging["current"] = moneys[1]["text"]
                    aging["please_pay_this_amount"] = moneys[2]["text"]
                    break

    return aging or None


def extract(pdf_path):
    """Returns {"line_items": [...], "summary": {...}} — the reference
    module's own shape, unchanged (adapted into this project's
    ExtractedStatement contract in main(), below, not here)."""
    line_items = []
    header_info = {}
    aging_summary = None
    total_pages = 0
    last_page_words = []

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        header_info = parse_header_info(pdf.pages[0].extract_text() or "")

        for page_num, page in enumerate(pdf.pages, start=1):
            words = page.extract_words()
            rows = group_rows(words)

            for row in rows:
                row = sorted(row, key=lambda w: w["x0"])
                dates = [w for w in row if DATE_RE.match(w["text"])]
                moneys = [w for w in row if MONEY_RE.match(w["text"])]
                others = [w for w in row if w not in dates and w not in moneys]

                if not dates or not moneys:
                    continue

                date = dates[0]["text"]
                document_transaction = " ".join(w["text"] for w in others)

                money_cols = {"purchases": "", "payments_credits": "", "balance": ""}
                for w in moneys:
                    money_cols[classify_money(w["x1"])] = w["text"]

                line_items.append({
                    "page": page_num,
                    "date": date,
                    "document_transaction": document_transaction,
                    "purchases": money_cols["purchases"],
                    "payments_credits": money_cols["payments_credits"],
                    "balance": money_cols["balance"],
                })

            if page_num == total_pages:
                last_page_words = words

        aging_summary = parse_aging_summary(last_page_words)

    computed_total = round(sum(parse_money(r["balance"]) or 0.0 for r in line_items), 2)

    summary = dict(header_info)
    if aging_summary:
        summary.update(aging_summary)
        printed_total = parse_money(aging_summary.get("please_pay_this_amount"))
    else:
        printed_total = None

    summary["total_computed"] = computed_total
    summary["total_printed"] = printed_total

    return {"line_items": line_items, "summary": summary}


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: extract_lia.py <pdf_path>"}))
        return 1

    pdf_path = sys.argv[1]
    try:
        result = extract(pdf_path)
        summary = result["summary"]
        lines = [
            {
                "invoice_ref": item["document_transaction"] or None,
                "ro_number": None,
                "amount": parse_money(item["balance"]),
                "date": normalize_date(item["date"]),
            }
            for item in result["line_items"]
        ]
        printed_total = summary.get("total_printed")
        statement = {
            "vendor_name_guess": "Lia Auto Group",
            "statement_period": normalize_date(summary.get("closing_date")),
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
