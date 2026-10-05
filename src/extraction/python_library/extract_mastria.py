"""
Extract a Mastria (Raynham, MA) customer account statement PDF into:
  1. <stem> - line items.csv  (structured transaction list)
  2. <stem> - summary.csv     (header info + printed "Please Pay This Amount")

CDK Global "ACCOUNTS RECEIVABLE STATEMENT TYPE 1 - AR1C" layout, real
embedded text -- the same template as Grappone (extract_grappone.py), whose
header / row-grouping / money helpers are reused here. Mastria's lines carry
two codes and no department name:

    06JUL26  1  32  320704G      810.88
    31AUG26  1  57  320704G               810.88
    07JUL26  1  32  CM320232GA            42.10
    28AUG26  4  32  203945S      257.75              257.75

  - dept_code (x0 ~114): the dealership -- 1 Buick GMC Cadillac (invoice
    suffix G), 2 (M), 4 Subaru (S), 6 Kia (K). Matching doesn't need it (the
    NetSuite entity list covers every rooftop), it is kept for display.
  - txn_code (x0 ~141): 32 = the original transaction (an invoice in
    Purchases, a CM credit memo in Payments & Credits); 57 = its closing
    twin, posted when the item is settled this period, for the same amount
    in the OPPOSITE column. Confirmed 2026-10-05 on the Quonset statement:
    134 rows, every 57 row pairs a 32 row of the same document (47 pairs),
    the 40 open items have only their 32 row, and no other codes appear.

Why this parser exists: through Claude the two code columns came back as
UNLABELED_TRANSACTION_CODE / _2 -- the same shape that let Claude glue
department text onto Grappone's document numbers on some runs -- and a 57
twin in the opposite column would make the matcher see a credit memo as a
bill (CM320232GA's twin sits in Purchases). Reading columns by position is
deterministic, and 57 rows keep their amounts in closing_purchases /
closing_payments instead of purchases / payments_credits, so every row still
reaches Bronze but matching only sees the original transactions.

Reconciliation: PLEASE PAY THIS AMOUNT (last page) equals sum(balance).
"""

import re
import sys

import pdfplumber

from extract_grappone import DATE_RE, MONEY_RE, clean_money, group_rows, parse_header_info, parse_please_pay

VENDOR_SIGNATURE = ["www.mastria.com"]

CLOSING_TXN_CODES = {"57"}

FIELDNAMES = ["page", "date", "dept_code", "txn_code", "document",
              "purchases", "payments_credits", "balance",
              "closing_purchases", "closing_payments"]


def parse_line(row):
    """One transaction line -> dict, or None if this row isn't one."""
    if len(row) < 3 or not DATE_RE.match(row[0]["text"]):
        return None
    item = {k: None for k in FIELDNAMES if k != "page"}
    item["date"] = row[0]["text"]
    doc_parts = []
    for w in row[1:]:
        x0, x1, t = w["x0"], w["x1"], w["text"]
        if MONEY_RE.match(t) and x0 >= 300:
            key = "purchases" if x1 <= 395 else "payments_credits" if x1 <= 475 else "balance"
            item[key] = clean_money(t)
        elif x0 < 130:
            item["dept_code"] = t
        elif x0 < 162:
            item["txn_code"] = t
        elif x0 < 320:
            doc_parts.append(t)
    item["document"] = "".join(doc_parts) or None
    if item["document"] is None:
        return None
    if item["txn_code"] in CLOSING_TXN_CODES:
        item["closing_purchases"], item["purchases"] = item["purchases"], None
        item["closing_payments"], item["payments_credits"] = item["payments_credits"], None
    return item


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    line_items = []
    with pdfplumber.open(pdf_path) as pdf:
        header = parse_header_info(pdf.pages[0].extract_text() or "")
        for page_num, page in enumerate(pdf.pages, start=1):
            for row in group_rows(page.extract_words()):
                item = parse_line(row)
                if item:
                    item["page"] = page_num
                    line_items.append({k: item.get(k) for k in FIELDNAMES})
        please_pay = parse_please_pay(pdf.pages[-1].extract_words())

    computed = round(sum(float(r["balance"]) for r in line_items if r["balance"]), 2)
    summary = dict(header)
    summary["total_printed"] = please_pay
    summary["total_computed"] = f"{computed:.2f}"
    summary["reconciles"] = please_pay is not None and round(float(please_pay), 2) == computed
    return {"line_items": line_items, "fieldnames": FIELDNAMES, "summary": summary, "full_text": None}


if __name__ == "__main__":
    result = extract(sys.argv[1] if len(sys.argv) > 1 else "Mastria Quonset 083026.pdf")
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
    for item in result["line_items"]:
        print(item)
