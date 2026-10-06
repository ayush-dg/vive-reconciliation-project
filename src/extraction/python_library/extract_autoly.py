"""
Extract an Autoly customer account statement PDF into line items + summary.

Autoly is the parts-management system many independent recyclers and parts
suppliers bill through -- Bow Auto Parts, Chuck's Douglassville, Ding's Auto
Parts, EL & M, Gear Six, Goyette's, My Auto Store, Stoystown, Tilghman's, ...
(2026-10-01 batch). Every one of them prints the same statement: the vendor's
own letterhead, a "Statement # / Period" block, an aging table (Open Items /
Unalloc. Items / Aged Amount), then one unruled ledger table

    Date | Transaction Type | Sls | Cust PO/Chk # | Charged | Paid | Unalloc. | Due | Description

and, on the last page, "Total due / Unallocated / Balance due". Because the
letterhead differs per vendor, the signature is that table header itself;
the vendor name is read from the letterhead (summary["vendor_name"]). Fenix
NE is an Autoly vendor too, but keeps its own extract_fenix.py -- registered
ahead of this module in extract_all.EXTRACTORS.

Columns are located from the header words on each page rather than fixed
pixel positions (extract_fenix.py's approach, measured on Fenix's PDFs):
  - pdfplumber returns the header's "Due" and "Description" as one word
    ("DueDescription"), and "Unalloc." can merge into it the same way; a
    merged header word is split into its known header names, each part
    getting its share of the word's width.
  - Charged, Paid, Unalloc. and Due amounts are right-aligned to their
    header's right edge, so an amount belongs to the column whose header
    right edge is nearest its own right edge (within MONEY_SNAP points).
  - Due is printed immediately before the Description text, so a Due value
    is often glued to it ("0.002017" = Due 0.00 + "2017 FORESTER ...");
    the amount is split off the front of such a word.
  - Date / Transaction Type / Sls / Cust PO/Chk # are left-aligned and
    bucketed by left edge.
A page without a header row reuses the previous page's columns. If no page
has a header row the statement yields no line items, and
01_document_intake.py retries it with the AI engine.

Rows are the dated ledger lines: "Invoice #<n>", "Credit #<n> for inv. <n>"
(the original invoice number sometimes wraps to the next line), and
"Payment: Check <n>" / "Payment: Credit Card ..." / "Payment: Bank Transfer"
(whose Description zone only repeats the payment text as a remittance stub,
so it is dropped -- same as extract_fenix.py). Aging rows, totals, notes and
footers are never rows.

Reconciliation (all 22 text-layer Autoly statements of 2026-10-01): sum(Due)
= printed "Total due", sum(Unalloc.) = "Unallocated", and Total due -
Unallocated = "Balance due" -- the amount the statement asks for, and what
the previous AI extraction stored as the printed total.
"""

import re
import sys

import pdfplumber

VENDOR_SIGNATURE = ["Cust PO/Chk # Charged Paid Unalloc."]

ROW_TOLERANCE = 3.0
# An amount's right edge may sit this far from its header's right edge.
MONEY_SNAP = 10.0

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
MONEY_RE = re.compile(r"^-?[\d,]*\d\.\d{2}-?$")
# A Due amount glued onto the start of its Description, e.g. "0.002017".
MONEY_PREFIX_RE = re.compile(r"^(-?[\d,]*\d\.\d{2})(\S+)$")
CONTINUATION_REF_RE = re.compile(r"^\d{4,10}$")
HEADER_NAMES = ("Description", "Transaction", "Unalloc.", "Charged", "PO/Chk", "Date", "Type", "Cust", "Paid", "Sls", "Due", "#")
_HEADER_PART_RE = re.compile("|".join(re.escape(h) for h in HEADER_NAMES))

FIELDNAMES = ["page", "date", "type", "reference_number", "original_invoice_ref",
              "sls", "po_chk_number", "charged", "paid", "unalloc", "due", "description"]


def clean_money(raw):
    """'1,325.00' -> '1325.00', blank -> None (see extract_fenix.clean_money)."""
    if not raw:
        return None
    return raw.replace(",", "")


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


def _split_word(word, parts):
    """Splits one pdfplumber word into consecutive parts, each getting its
    share of the word's width by character count."""
    width = (word["x1"] - word["x0"]) / max(len(word["text"]), 1)
    out, x = [], word["x0"]
    for part in parts:
        out.append(dict(word, text=part, x0=x, x1=x + width * len(part)))
        x += width * len(part)
    return out


def _header_parts(word):
    parts = _HEADER_PART_RE.findall(word["text"])
    if len(parts) > 1 and "".join(parts) == word["text"]:
        return _split_word(word, parts)
    return [word]


def find_columns(words):
    """The ledger header row's column anchors, or None if this page has no
    header row. Requires every header name the rows are read by."""
    for row in group_rows(words):
        parts = [p for w in row for p in _header_parts(w)]
        by_name = {}
        for p in parts:
            by_name.setdefault(p["text"], p)
        if not all(n in by_name for n in ("Date", "Transaction", "Sls", "Cust", "Charged", "Paid", "Unalloc.", "Due")):
            continue
        return {
            "top": min(p["top"] for p in parts),
            "transaction_x0": by_name["Transaction"]["x0"],
            "sls_x0": by_name["Sls"]["x0"],
            "po_x0": by_name["Cust"]["x0"],
            "charged_x0": by_name["Charged"]["x0"],
            "money_x1": {
                "charged": by_name["Charged"]["x1"],
                "paid": by_name["Paid"]["x1"],
                "unalloc": by_name["Unalloc."]["x1"],
                "due": by_name["Due"]["x1"],
            },
            "due_x0": by_name["Due"]["x0"],
        }
    return None


def _money_column(word, cols):
    if not MONEY_RE.match(word["text"]):
        return None
    name, x1 = min(cols["money_x1"].items(), key=lambda kv: abs(kv[1] - word["x1"]))
    return name if abs(x1 - word["x1"]) <= MONEY_SNAP else None


def classify(word, cols):
    if word["x0"] < cols["transaction_x0"] - 2:
        return "date"
    if word["x0"] < cols["sls_x0"] - 2:
        return "transaction_type"
    if word["x0"] < cols["po_x0"] - 2:
        return "sls"
    column = _money_column(word, cols)
    if column:
        return column
    if word["x0"] < cols["charged_x0"]:
        return "po_chk"
    if word["x0"] >= cols["due_x0"] - 2:
        return "description"
    return "unplaced"


def _row_words(row, cols):
    """The row's words, with a Due amount glued to its Description split off.
    Only a word starting inside the Due column can be one -- Description
    text starts after the Due header's right edge."""
    out = []
    for w in row:
        m = None if MONEY_RE.match(w["text"]) else MONEY_PREFIX_RE.match(w["text"])
        if m and w["x0"] < cols["money_x1"]["due"]:
            out.extend(_split_word(w, m.groups()))
        else:
            out.append(w)
    return out


def _rows_text(rows):
    return [" ".join(w["text"] for w in sorted(r, key=lambda w: w["x0"])) for r in rows]


def parse_header_info(page1):
    words = page1.extract_words()
    text = page1.extract_text() or ""
    info = {}
    anchor = next((w for w in words if w["text"] == "Statement"), None)
    letterhead = [w for w in words if w["x0"] < 300 and (anchor is None or w["top"] < anchor["top"] - 2)]
    lines = _rows_text(group_rows(letterhead))
    for key, line in zip(("vendor_name", "vendor_address", "vendor_city_state_zip"), lines):
        info[key] = line

    m = re.search(r"Statement\s*#\s*(\S+)", text)
    if m:
        info["statement_number"] = m.group(1)
    m = re.search(r"Period\s+(\d{2}/\d{2}/\d{2})\s*-\s*(\d{2}/\d{2}/\d{2})", text)
    if m:
        info["period_start"], info["period_end"] = m.groups()

    # Customer block: left of the aging table, from the "Open Items" row down
    # to the aging table's Total row.
    open_word = next((w for w in words if w["text"] == "Open"), None)
    total_word = next((w for w in words if w["text"] == "Total" and open_word and w["top"] > open_word["top"]), None)
    if open_word:
        bottom = total_word["top"] if total_word else open_word["top"] + 60
        block = [w for w in words if open_word["top"] - 3 <= w["top"] < bottom and 60 < w["x0"] and w["x1"] < 340]
        for key, line in zip(("customer_name", "billing_address", "billing_city_state_zip"), _rows_text(group_rows(block))):
            info[key] = line
    return info


def parse_totals(full_text):
    info = {}
    for key, pattern in (("total_due_printed", r"Total due\s+(-?[\d,]+\.\d{2})"),
                         ("unallocated_printed", r"Unallocated\s+(-?[\d,]+\.\d{2})"),
                         ("balance_due_printed", r"Balance due\s+(-?[\d,]+\.\d{2})")):
        found = re.findall(pattern, full_text)
        if found:
            info[key] = found[-1]
    if "balance_due_printed" not in info:
        # The aging table's own Total row: Open Items / Unalloc. Items / Aged
        # Amount -- the same three figures in the same order.
        found = re.findall(r"(?m)^Total\s+(-?[\d,]+\.\d{2})\s+(-?[\d,]+\.\d{2})\s+(-?[\d,]+\.\d{2})\s*$", full_text)
        if found:
            info.setdefault("total_due_printed", found[-1][0])
            info.setdefault("unallocated_printed", found[-1][1])
            info["balance_due_printed"] = found[-1][2]
    return info


def _parse_row(cells, page_num):
    tx_text = " ".join(w["text"] for w in sorted(cells.get("transaction_type", []), key=lambda w: w["x0"]))
    first = tx_text.split(" ")[0].rstrip(":").upper() if tx_text else ""
    tx_type = first if first in ("INVOICE", "CREDIT", "PAYMENT") else (first or "")
    if tx_type == "PAYMENT":
        m = re.search(r"Check\s+(\S+)", tx_text)
    else:
        m = re.search(r"#\s*(\S+)", tx_text)
    reference_number = m.group(1) if m else ""
    m = re.search(r"for\s+inv\.?\s*([A-Za-z0-9-]+)", tx_text, re.IGNORECASE)
    original_invoice_ref = m.group(1) if m else ""

    def joined(key):
        return " ".join(w["text"] for w in sorted(cells.get(key, []), key=lambda w: w["x0"]))

    # A Payment row's Description zone only repeats the payment text (a
    # remittance stub) -- not transaction data.
    description = "" if tx_type == "PAYMENT" else joined("description")
    return {
        "page": page_num,
        "date": joined("date"),
        "type": tx_type,
        "reference_number": reference_number,
        "original_invoice_ref": original_invoice_ref,
        "sls": joined("sls"),
        "po_chk_number": joined("po_chk"),
        "charged": clean_money(joined("charged")),
        "paid": clean_money(joined("paid")),
        "unalloc": clean_money(joined("unalloc")),
        "due": clean_money(joined("due")),
        "description": description,
    }


def extract(pdf_path):
    """Returns {"line_items": [...], "fieldnames": [...], "summary": {...}, "full_text": None}."""
    line_items = []
    unplaced = []
    pages_without_header = 0
    texts = []

    with pdfplumber.open(pdf_path) as pdf:
        header_info = parse_header_info(pdf.pages[0])
        cols = None
        for page_num, page in enumerate(pdf.pages, start=1):
            texts.append(page.extract_text() or "")
            words = page.extract_words()
            page_cols = find_columns(words)
            if page_cols:
                cols = page_cols
                body = [w for w in words if w["top"] > page_cols["top"] + ROW_TOLERANCE]
            elif cols:
                pages_without_header += 1
                body = words
            else:
                pages_without_header += 1
                continue

            for row in group_rows(body):
                cells = {}
                for w in _row_words(row, cols):
                    cells.setdefault(classify(w, cols), []).append(w)
                date = " ".join(w["text"] for w in cells.get("date", []))
                if DATE_RE.match(date):
                    for w in cells.pop("unplaced", []):
                        unplaced.append({"page": page_num, "date": date, "text": w["text"]})
                    line_items.append(_parse_row(cells, page_num))
                    continue
                # The wrapped original-invoice number of a Credit row: a bare
                # number alone in the Transaction Type column.
                tx_only = cells.get("transaction_type", [])
                if tx_only and set(cells) == {"transaction_type"} and line_items:
                    text = " ".join(w["text"] for w in tx_only)
                    if CONTINUATION_REF_RE.match(text) and line_items[-1]["type"] == "CREDIT" \
                            and not line_items[-1]["original_invoice_ref"]:
                        line_items[-1]["original_invoice_ref"] = text

    totals = parse_totals("\n".join(texts))

    def to_float(s):
        return float(s.rstrip("-")) * (-1 if s.endswith("-") else 1) if s else 0.0

    computed_due = round(sum(to_float(r["due"]) for r in line_items), 2)
    computed_unalloc = round(sum(to_float(r["unalloc"]) for r in line_items), 2)
    printed_balance = float(totals["balance_due_printed"].replace(",", "")) if totals.get("balance_due_printed") else None

    summary = dict(header_info)
    summary.update(totals)
    summary["total_due_computed"] = f"{computed_due:,.2f}"
    summary["unallocated_computed"] = f"{computed_unalloc:,.2f}"
    summary["reconciles"] = printed_balance is not None and round(computed_due - computed_unalloc, 2) == printed_balance
    summary["pages_without_header"] = pages_without_header
    summary["unplaced_values"] = unplaced

    return {
        "line_items": line_items,
        "fieldnames": FIELDNAMES,
        "summary": summary,
        "full_text": None,
    }


if __name__ == "__main__":
    result = extract(sys.argv[1])
    print(f"Line items extracted: {len(result['line_items'])}")
    print(f"Summary: {result['summary']}")
    for item in result["line_items"]:
        print(item)
