"""
Extract a CDK "eF320-Accounts Receivable Statement" PDF into line items + summary.

Why (2026-10-25): on dev, the AI read of all three Faulkner statements (Honda,
Nissan, Subaru of Harrisburg) returned the six column names but no rows, and
the pdfplumber fallback found none either -- 0 rows, jobs failed. The layout is
one printed line per transaction, so it is read here deterministically from the
text layer, with no AI call. The same form is printed by other CDK dealers
(Morong Falmouth, Fette Ford -- same positions).

Layout (real embedded text, no ruled table; measured on all six PDFs seen):
  header      DATE | DOCUMENT/TRANSACTION | PURCHASES ($) | PAYMENTS & CREDITS ($) | BALANCE DUE ($)
  sub-header  [COMPANY ID] JOURNAL ID | REFERENCE # | PREVIOUS BALANCE
  rows        08-28-2026  32  32  518306      41.62
  aging       CURRENT ($) | OVER 30 DAYS ($) | ... | OVER 120 DAYS ($) | BALANCE DUE ($)
              0.00          41.62              ...   0.00               41.62
  footer      FINANCE CHARGES ... a periodic rate of 1.50% per month ...

Rules:
  - a dated line that prints a REFERENCE # is a row. Its ids go to the
    sub-header column they are printed under (left-aligned: COMPANY ID,
    JOURNAL ID, REFERENCE #); each amount goes to the money column whose
    header ends nearest the amount's right edge (amounts are right-aligned:
    every one seen ends at x 363.9, under PURCHASES ($)).
  - a dated line with no reference and ONE amount, under BALANCE DUE, is an
    opening-balance line (the 2026-10-19 rule, pdf_row_match.
    _opening_balance_line): it is not a row -- left to the gate exactly as
    with the AI's rows -- and is reported in the summary.
  - the printed total is the aging line's BALANCE DUE ($).
  - anything else printed between the sub-header and the aging header (an
    undated line, an amount that sits under no money column, a second amount
    in one column), a page with dated lines but no header, or no dealer name
    above the address block means a variant this parser has not seen: NO
    rows are returned, and the intake falls back to the AI engine as before
    (01_document_intake.py: "Python-library extractor returned 0 line
    items"). summary["parse_problem"] says why.

Field names are the printed headers, so the rows reach Silver through the
vendors' existing vendor_field_mapping.csv rows (FAULKNER, FETTE,
MORONG_FALMOUTH: DATE, REFERENCE #, PURCHASES ($), ...), the names the AI
path stored for this form. Empty columns are None, not "" (see
extract_lia.py: Silver types a line by which raw amount is present).
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["eF320-Accounts Receivable Statement"]

ROW_TOLERANCE = 2.5      # pt; words this close vertically are one printed line
ID_TOLERANCE = 12.0      # pt; an id starts within this of its sub-header word
DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
MONEY_RE = re.compile(r"^-?[\d,]+\.\d{2}-?$")

MONEY_COLUMNS = ("PURCHASES ($)", "PAYMENTS & CREDITS ($)", "BALANCE DUE ($)")
ID_COLUMNS = (("COMPANY", "COMPANY ID"), ("JOURNAL", "JOURNAL ID"), ("REFERENCE", "REFERENCE #"))
AGING_KEYS = ("aging_current", "aging_over_30", "aging_over_60", "aging_over_90", "aging_over_120",
              "aging_balance_due")
FIELDNAMES = ["page", "DATE", "COMPANY ID", "JOURNAL ID", "REFERENCE #"] + list(MONEY_COLUMNS)


class LayoutNotRecognised(Exception):
    """A line or page this parser does not know -- no rows are returned."""


def parse_money(s):
    """'1,234.56' -> 1234.56; a trailing or leading minus is negative."""
    if not s:
        return None
    s = s.strip()
    negative = s.endswith("-") or s.startswith("-")
    s = s.strip("-").replace(",", "")
    return -float(s) if negative else float(s)


def group_rows(words):
    """Words grouped into printed lines by their top, anchored to the first
    word of each line (extract_lia.py's technique), each line sorted by x0."""
    rows = []
    current_top = None
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if current_top is None or abs(w["top"] - current_top) > ROW_TOLERANCE:
            rows.append([])
            current_top = w["top"]
        rows[-1].append(w)
    return [sorted(r, key=lambda w: w["x0"]) for r in rows]


def _texts(row):
    return [w["text"] for w in row]


def _is_header(row):
    t = _texts(row)
    return "DATE" in t and "PURCHASES" in t and "PAYMENTS" in t and "BALANCE" in t


def _is_aging_header(row):
    t = _texts(row)
    return "CURRENT" in t and t.count("OVER") >= 3


def _money_edges(header):
    """{money column: right edge of its printed header phrase}, e.g.
    "PURCHASES ($)" ends at the x1 of its "($)"."""
    t = _texts(header)
    starts = {"PURCHASES ($)": t.index("PURCHASES"), "PAYMENTS & CREDITS ($)": t.index("PAYMENTS"),
              "BALANCE DUE ($)": t.index("BALANCE")}
    order = sorted(starts.items(), key=lambda kv: kv[1])
    edges = {}
    for k, (name, i) in enumerate(order):
        end = order[k + 1][1] if k + 1 < len(order) else len(header)
        edges[name] = max(w["x1"] for w in header[i:end])
    return edges


def _id_starts(sub_header):
    """{id column: x0 of its sub-header word} for the id columns printed."""
    t = _texts(sub_header)
    return {name: sub_header[t.index(word)]["x0"] for word, name in ID_COLUMNS if word in t}


def _money_column(word, edges):
    """The money column whose header ends nearest this right-aligned amount;
    None when it is nearer the midpoint between two columns than either."""
    ranked = sorted(edges.items(), key=lambda kv: abs(kv[1] - word["x1"]))
    best = ranked[0]
    if len(ranked) > 1:
        gap = abs(ranked[1][1] - best[1])
        if abs(best[1] - word["x1"]) > gap / 2:
            return None
    return best[0]


def _parse_dated_line(row, edges, id_starts, page_num):
    """(item, None) for a transaction row, (None, opening) for an
    opening-balance line; raises LayoutNotRecognised otherwise."""
    line = " ".join(_texts(row))
    item = {"page": page_num, "DATE": row[0]["text"], **{name: None for _, name in ID_COLUMNS},
            **{name: None for name in MONEY_COLUMNS}}
    for w in row[1:]:
        if MONEY_RE.match(w["text"]):
            column = _money_column(w, edges)
            if column is None or item[column] is not None:
                raise LayoutNotRecognised(f"amount {w['text']} not under one money column: {line!r}")
            item[column] = w["text"]
            continue
        near = [(abs(x0 - w["x0"]), name) for name, x0 in id_starts.items() if abs(x0 - w["x0"]) <= ID_TOLERANCE]
        if not near:
            raise LayoutNotRecognised(f"{w['text']!r} is under no id column: {line!r}")
        name = min(near)[1]
        if item[name] is not None:
            raise LayoutNotRecognised(f"two values under {name}: {line!r}")
        item[name] = w["text"]
    amounts = [name for name in MONEY_COLUMNS if item[name] is not None]
    if item["REFERENCE #"]:
        if not amounts:
            raise LayoutNotRecognised(f"dated line with no amount: {line!r}")
        return item, None
    if amounts == ["BALANCE DUE ($)"] and not item["COMPANY ID"] and not item["JOURNAL ID"]:
        return None, {"page": page_num, "date": item["DATE"], "amount": item["BALANCE DUE ($)"]}
    raise LayoutNotRecognised(f"dated line with no reference number: {line!r}")


def _letterhead(rows):
    """(dealer name, customer number, closing date, customer block lines)
    from page 1: the dealer name is the first line printed in the middle
    band of the letterhead (between "REMIT TO:" on the left and "ACCOUNTS
    DUE / AND PAYABLE BY THE" on the right) in the larger font; the address
    lines under it are smaller. The customer block is the left-hand lines
    under CLOSING DATE, above the remittance stub."""
    cust_no = closing = None
    cust_top = closing_top = stub_top = None
    for row in rows:
        t = _texts(row)
        if t[:2] == ["CUST", "NO"] and len(t) >= 3:
            cust_no, cust_top = t[-1], row[0]["top"]
        if t[:2] == ["CLOSING", "DATE"] and len(t) >= 3:
            closing, closing_top = t[-1], row[0]["top"]
        if stub_top is None and ("ENCLOSED" in t or t[:3] == ["PLEASE", "RETURN", "THIS"]):
            stub_top = row[0]["top"]
    name = None
    for row in rows:
        if cust_top is not None and row[0]["top"] >= cust_top:
            break
        band = [w for w in row if w["x0"] >= 150 and w["x1"] <= 460 and w["bottom"] - w["top"] >= 9.5]
        if band:
            name = " ".join(w["text"] for w in band)
            break
    block = []
    if closing_top is not None:
        for row in rows:
            if row[0]["top"] <= closing_top + ROW_TOLERANCE:
                continue
            if stub_top is not None and row[0]["top"] >= stub_top - ROW_TOLERANCE:
                break
            left = [w for w in row if w["x1"] < 300]
            if left:
                block.append(" ".join(w["text"] for w in left))
    return name, cust_no, closing, block


def _parse(pdf):
    line_items, openings = [], []
    summary = {"total_pages": len(pdf.pages)}
    balance_due = aging = None
    for page_num, page in enumerate(pdf.pages, start=1):
        rows = group_rows(page.extract_words())
        if page_num == 1:
            name, cust_no, closing, block = _letterhead(rows)
            if not name:
                raise LayoutNotRecognised("no dealer name in the letterhead")
            summary.update(vendor_name=name, customer_number=cust_no, closing_date=closing)
            if block:
                summary["customer_name"] = block[0]
                if len(block) > 1:
                    summary["billing_city_state_zip"] = block[-1]
        header_i = next((i for i, r in enumerate(rows) if _is_header(r)), None)
        if header_i is None:
            if any(DATE_RE.match(r[0]["text"]) for r in rows):
                raise LayoutNotRecognised(f"page {page_num} has dated lines but no column header")
            continue
        edges = _money_edges(rows[header_i])
        if header_i + 1 >= len(rows) or "REFERENCE" not in _texts(rows[header_i + 1]):
            raise LayoutNotRecognised(f"page {page_num}: no COMPANY ID / JOURNAL ID / REFERENCE # sub-header")
        sub_header = rows[header_i + 1]
        if any(MONEY_RE.match(w["text"]) for w in sub_header):
            raise LayoutNotRecognised(f"page {page_num}: an amount is printed on the PREVIOUS BALANCE line")
        id_starts = _id_starts(sub_header)
        i = header_i + 2
        while i < len(rows) and not _is_aging_header(rows[i]):
            row = rows[i]
            if not DATE_RE.match(row[0]["text"]):
                raise LayoutNotRecognised(f"page {page_num}: undated line in the table: {' '.join(_texts(row))!r}")
            item, opening = _parse_dated_line(row, edges, id_starts, page_num)
            if item:
                line_items.append(item)
            else:
                openings.append(opening)
            i += 1
        if i + 1 < len(rows) and _is_aging_header(rows[i]):
            amounts = [w["text"] for w in rows[i + 1] if MONEY_RE.match(w["text"])]
            if len(amounts) == len(AGING_KEYS):
                aging = dict(zip(AGING_KEYS, amounts))
                balance_due = amounts[-1]
    if aging:
        summary.update(aging)
    summary["balance_due_printed"] = balance_due
    if openings:
        summary["opening_balance_lines"] = openings
    return line_items, summary


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    with pdfplumber.open(pdf_path) as pdf:
        try:
            line_items, summary = _parse(pdf)
        except LayoutNotRecognised as e:
            line_items, summary = [], {"total_pages": len(pdf.pages), "parse_problem": str(e)}
    net = sum((parse_money(r["PURCHASES ($)"]) or 0.0) - abs(parse_money(r["PAYMENTS & CREDITS ($)"]) or 0.0)
              for r in line_items)
    printed = parse_money(summary.get("balance_due_printed"))
    summary["total_computed"] = f"{net:,.2f}"
    summary["reconciles"] = printed is not None and round(net - printed, 2) == 0.0
    return {"line_items": line_items, "fieldnames": FIELDNAMES, "summary": summary, "full_text": None}


if __name__ == "__main__":
    result = extract(sys.argv[1])
    print(f"Line items extracted: {len(result['line_items'])}")
    for item in result["line_items"]:
        print(f"  {item}")
    print(f"Summary: {result['summary']}")
