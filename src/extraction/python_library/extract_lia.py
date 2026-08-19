"""
Extract Lia Auto Group (Lia Group Payables LLC) AR statement PDF into:
  1. Lia Vestal - line items.csv  (structured transaction list)
  2. Lia Vestal - summary.csv     (header info + aging summary + printed total)

This is the same underlying statement-generator software family as the Fred
Beans / extract_statement.py layout - both print "Copyright 2014 CDK Global,
LLC ACCOUNTS RECEIVABLE STATEMENT" - but this document is stamped
"TYPE 1 - AR1C" rather than Fred Beans' "TYPE 3 - AR3C". AR1C is a much
simpler layout: a single running list of transactions (no dual
invoice/remittance-stub columns, no two-digit transaction-type codes), and
verification showed each row's "Balance" value is simply that row's own
Purchases amount (or, for a credit memo, the negative of its Payments &
Credits amount) rather than a cumulative running balance - so it's really an
"amount for this row" column, similar in spirit to how Fred Beans' amount_due
column worked, but here there's no prior-row dependency at all: the printed
per-row balance IS the row's amount, and they sum directly to the account
total (no PREVIOUS BALANCE carry-forward was present on this statement).

This PDF has real embedded text (confirmed via pdfplumber probe - not a
scan). pdfplumber's native extract_table() finds nothing usable (no ruled
table lines), so line items are reconstructed from extract_words() using a
row-grouping + x1 (right-edge) money-column classifier, the same general
technique as extract_statement.py: amounts are right-aligned so their right
edge clusters cleanly by column, while their left edge shifts with digit
count (e.g. "1,403.95" vs "69.00").

Negative amounts print with a TRAILING minus sign (e.g. "50.00-" for the
credit memo CM153454HA), not a leading one - confirmed by inspecting that
row's Balance token directly.

The letter-spaced "Li a G ro u p P a y ab l es L L C" logo text (an
extraction artifact of a stylized font, not something to regex against) is
irrelevant to vendor detection here since the literal, normally-spaced
string "LIA AUTO GROUP" appears near the bottom of every page, above the
CDK copyright line.
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["LIA AUTO GROUP", "Lia Group Payables"]

ROW_TOLERANCE = 2.5  # px tolerance for grouping words into the same row

DATE_RE = re.compile(r"^\d{2}[A-Z]{3}\d{2}$")
MONEY_RE = re.compile(r"^-?[\d,]+\.\d{2}-?$")

# Money column boundaries by right-edge (x1), measured from this document's
# word positions (see module docstring / extract_statement.py precedent for
# why x1 rather than x0 is used: amounts are right-aligned).
MONEY_COLUMNS = [
    ("purchases", 390),
    ("payments_credits", 470),
    ("balance", 10_000),
]

FIELDNAMES = ["page", "date", "document_transaction", "purchases", "payments_credits", "balance"]


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


def group_rows(words):
    """Group words into rows by their 'top' coordinate, anchored to the
    first word's top (matches extract_statement.py's technique)."""
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
    # "CLOSING DATE" label sits beside the customer-name line, so the
    # closing date (e.g. "31JUL26") is appended to the end of that line
    # rather than printing on its own line.
    m = re.search(r"CLOSING DATE\s*\n(.+?)\s+(\d{2}[A-Z]{3}\d{2})\n(.+)\n(.+)", page1_text)
    if m:
        info["customer_name"] = m.group(1).strip()
        info["closing_date"] = m.group(2).strip()
        info["billing_address"] = m.group(3).strip()
        info["billing_city_state_zip"] = m.group(4).strip()
    m = re.search(r"PAGE\s+(\d+)", page1_text)
    if m:
        info["page_no"] = m.group(1)
    return info


def parse_aging_summary(words):
    """The aging totals only print on the last page (earlier pages show the
    labels with no numbers, since the statement is still accumulating).
    Locate the "PAST DUE / CURRENT / ... PLEASE PAY" label row and the
    "OVER 30 / 60 / 90 / 120" label row, then pull the money tokens out of
    the row immediately following each (see module docstring)."""
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
        if texts.count("OVER") >= 3:
            for j in range(i + 1, min(i + 3, len(rows))):
                moneys = sorted((w for w in rows[j] if MONEY_RE.match(w["text"])), key=lambda w: w["x0"])
                if len(moneys) >= 4:
                    aging["over_30"] = moneys[0]["text"]
                    aging["over_60"] = moneys[1]["text"]
                    aging["over_90"] = moneys[2]["text"]
                    aging["over_120"] = moneys[3]["text"]
                    break

    return aging or None


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    line_items = []
    header_info = {}
    aging_summary = None
    total_pages = 0

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

                # A genuine transaction row has both a transaction date and
                # at least one money amount. A date alone isn't enough: the
                # "CLOSING DATE" header block prints the customer name and
                # closing date on one line (e.g. "VIVE COLL VESTAL 31JUL26"),
                # which would otherwise be mistaken for a transaction row.
                # Header rows, the "PREVIOUS BALANCE" label row, and the
                # aging summary block all lack a date, a money amount, or
                # both.
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
                aging_summary = parse_aging_summary(words)

    computed_total = round(sum(parse_money(r["balance"]) or 0.0 for r in line_items), 2)

    summary = dict(header_info)
    summary["total_pages"] = total_pages
    if aging_summary:
        summary.update(aging_summary)
        printed_total = parse_money(aging_summary.get("please_pay_this_amount"))
    else:
        # Fall back to summing the aging buckets if no single total printed.
        printed_total = None

    if printed_total is None and aging_summary:
        bucket_sum = sum(
            parse_money(aging_summary.get(k)) or 0.0
            for k in ("past_due", "current")
        )
        printed_total = round(bucket_sum, 2)

    summary["total_computed"] = f"{computed_total:,.2f}"
    summary["total_printed"] = f"{printed_total:,.2f}" if printed_total is not None else None
    summary["reconciles"] = (
        printed_total is not None and round(computed_total - printed_total, 2) == 0.0
    )

    return {
        "line_items": line_items,
        "fieldnames": FIELDNAMES,
        "summary": summary,
        "full_text": None,
    }


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "Lia Vestal.pdf"
    result = extract(pdf_path)
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
