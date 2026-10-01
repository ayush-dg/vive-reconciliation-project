"""
Extract a Grappone (Concord, NH) customer account statement PDF into:
  1. <stem> - line items.csv  (structured transaction list)
  2. <stem> - summary.csv     (header info + printed "Please Pay This Amount")

CDK Global "ACCOUNTS RECEIVABLE STATEMENT TYPE 1 - AR1C" layout, real
embedded text (confirmed via pdfplumber on 2 real August 2026 statements,
customerinvoice (4)/(5), Prestige Auto Body). Same template as Clinton
Honda's and Parts by Cochran's statements, but Grappone's lines also print
a DEPARTMENT NAME between the department code and the document number:

    06JUL26  13  GRAPPONE H   415526H   710.64
    10AUG26  16  FORD ACCTG   980339F            1,538.42
    20JUL26  80  MGMT ACCTG   415136H              84.61

Why this parser exists (2026-10-01): these statements used to go to Claude,
which split those columns differently on every run -- the document number
came back as "415136H", "GRAPPONE H 415136H", "13 GRAPPONE H 415136H" or
"FORD ACCTG 978881F" for the same kind of line, none of which but the first
is a NetSuite tranid. Dev reconciled the two August statements 0/53 and
5/46; with the department text removed, 94 of the 99 exception lines tie
out under entity 10000. Reading columns by position makes it deterministic.

Columns are bucketed by word position, measured on these statements:
  - date: x0 < 95 ("26JUN26")
  - dept_code: 95 <= x0 < 118 ("13", "14", "16", "80")
  - dept_name: 118 <= x0 < 205 ("GRAPPONE H", "GRAPPONE M", "FORD ACCTG",
    "MGMT ACCTG")
  - document: 205 <= x0 < 320 -- the NetSuite tranid verbatim, incl. the
    department suffix letter (415136H, 67115M, 980339F) and credit-memo
    prefix (CM415136H, CM67108MA)
  - amounts, by right edge (x1): purchases <= 395, payments_credits <= 475,
    balance beyond. A trailing "-" means negative ("4.42-" -> "-4.42").
Blank cells are None, not "" -- a "" raw value would make Silver's
sign-based line_type call a payment/credit row a CHARGE (see
extract_allstar.py's docstring).

"Totals: 14 - GRAPPONE MAZDA ..." department subtotal lines and the
"PREVIOUS BALANCE" line are not transactions and are skipped (their first
word isn't a date). Each paid invoice is reprinted on a later payment line
with the same document number (e.g. 415526H charge 06JUL26, payment
20AUG26) -- kept, as on the printed page; fabric_matching's
_drop_payment_closing_lines() drops the payment twin at matching time.

Reconciliation: the printed "PLEASE PAY THIS AMOUNT" (last page) equals
the sum of the Balance column.
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["www.grappone.com"]

ROW_TOLERANCE = 2.5
DATE_RE = re.compile(r"^\d{2}[A-Z]{3}\d{2}$")
MONEY_RE = re.compile(r"^[\d,]+\.\d{2}-?$")

FIELDNAMES = ["page", "date", "dept_code", "dept_name", "document",
              "purchases", "payments_credits", "balance"]


def clean_money(raw):
    """'1,476.40' -> '1476.40', '4.42-' -> '-4.42', '' -> None."""
    s = (raw or "").strip().replace(",", "")
    if not s:
        return None
    if s.endswith("-"):
        return f"-{s[:-1]}"
    return s


def group_rows(words):
    rows = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(w["top"] - rows[-1][0]["top"]) <= ROW_TOLERANCE:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w["x0"]) for r in rows]


def parse_line(row):
    """One transaction line -> dict, or None if this row isn't one."""
    if len(row) < 3 or not DATE_RE.match(row[0]["text"]):
        return None
    item = {"date": row[0]["text"], "dept_code": None, "dept_name": None, "document": None,
            "purchases": None, "payments_credits": None, "balance": None}
    name_parts, doc_parts = [], []
    for w in row[1:]:
        x0, x1, t = w["x0"], w["x1"], w["text"]
        if MONEY_RE.match(t) and x0 >= 300:
            key = "purchases" if x1 <= 395 else "payments_credits" if x1 <= 475 else "balance"
            item[key] = clean_money(t)
        elif x0 < 118:
            item["dept_code"] = t
        elif x0 < 205:
            name_parts.append(t)
        elif x0 < 320:
            doc_parts.append(t)
    item["dept_name"] = " ".join(name_parts) or None
    item["document"] = "".join(doc_parts) or None
    if item["document"] is None:
        return None
    return item


def parse_header_info(page1_text):
    info = {}
    lines = [l.strip() for l in page1_text.splitlines()]
    m = re.search(r"ACCT\.\s*NO\s*\n\s*(\S+)", page1_text)
    if m:
        info["account_no"] = m.group(1)
    for i, line in enumerate(lines):
        if line == "CLOSING DATE" and i + 1 < len(lines):
            m = re.match(r"^(.*\S)\s+(\d{2}[A-Z]{3}\d{2})$", lines[i + 1])
            if m:
                info["customer_name"] = m.group(1)
                info["statement_date"] = m.group(2)
            # Address block: the lines after the customer line up to
            # "AMOUNT ENCLOSED", skipping a stray bare page-count digit.
            block = []
            for nxt in lines[i + 2:]:
                if nxt.startswith("AMOUNT ENCLOSED"):
                    break
                if nxt and not nxt.isdigit():
                    block.append(nxt)
            if len(block) >= 2:
                info["billing_address"] = block[-2]
                info["billing_city_state_zip"] = block[-1]
            break
    return info


def parse_please_pay(last_page_words):
    """The amount under "PLEASE PAY THIS AMOUNT" on the last page: the
    right-most money value on the row just below the "PLEASE PAY" label."""
    rows = group_rows(last_page_words)
    for idx, row in enumerate(rows):
        texts = [w["text"] for w in row]
        if "PLEASE" in texts and "PAY" in texts:
            for nxt in rows[idx + 1: idx + 3]:
                money = [w for w in nxt if MONEY_RE.match(w["text"])]
                if money:
                    return clean_money(max(money, key=lambda w: w["x0"])["text"])
    return None


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
    result = extract(sys.argv[1] if len(sys.argv) > 1 else "customerinvoice (4).pdf")
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
    for item in result["line_items"]:
        print(item)
