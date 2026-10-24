"""
due_column.py

Due amount read out of a merged "Due Description" cell (C3, 2026-10-20). Autoly statements print
the ledger  Date | Transaction Type | Sls | Cust PO/Chk # | Charged | Paid | Unalloc. | Due | Description
and the printed total is sum(Due) - sum(Unalloc.). When the AI extraction returns Due and
Description as ONE column ("Due Description"), each open invoice's Due amount lands at the front of
its description ("225.00 (YOR) 2019 SENTRA L Front Door") and the open-balance check has nothing to
add up. (Chuck's Noakers STMT-0D64E1F3: a scan, so extract_autoly -- which needs a text layer --
never saw it and the AI engine read it.)

plan_due_column_corrections() only PLANS. It refuses -- changing nothing -- unless all of this holds:
  - the extraction has one "Due Description" column (no separate Due column) and Charged, Paid and
    Unalloc. columns, and no row already holds a Due (amount_due) value;
  - the PDF (text layer, or Tesseract OCR with word positions for a scan -- pdf_row_match's own
    read) prints the header with Charged, Paid, Unalloc., Due and Description as separate words;
  - every extracted row matches exactly one dated printed line (date + reference) and every dated
    printed line exactly one row;
  - on every line, each printed Charged / Paid / Unalloc. cell equals the row's extracted value;
  - a row whose cell starts with an amount: that amount equals the line's own printed Due cell to the
    cent, the rest of the cell is exactly the printed description, and the row has a Charged amount
    the Due fits (same sign, not larger); every other row prints no Due;
  - sum(printed Due) - sum(printed Unalloc.) equals the printed total exactly (and a printed Totals
    line, if any, agrees).
The caller (notebooks/01_document_intake.py apply_arithmetic_validation) applies a plan only to a
statement that fails the gate, on a copy first, and keeps it only if the corrected rows' open-balance
equation reconciles exactly and the whole gate then passes.

apply_due_column_corrections() sets amount_due and splits the raw cell into "Due" (the amount) and
"Due Description" (the text), in place, so Bronze holds the corrected row.

DUE_COLUMN_CORRECTION_ENABLED=false switches it off (default on).
"""

import os
import re
from typing import Optional

ENV_FLAG = "DUE_COLUMN_CORRECTION_ENABLED"
MERGED_KEY = "DUEDESCRIPTION"
NOT_APPLICABLE = "the extraction has no merged Due Description column with Charged / Paid / Unalloc."
_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
_LEADING_RE = re.compile(r"^\s*(-?[\d,]*\d\.\d{2})\s+(\S.*)$")
_SNAP = 10.0        # pt: an amount's right edge must be this close to its header's right edge
_MARGIN = 6.0       # pt: ...and this much closer than to any other amount column
_CENT = 0.005
_COLUMNS = ("Charged", "Paid", "Unalloc.", "Due")


def enabled() -> bool:
    return os.getenv(ENV_FLAG, "true").strip().lower() != "false"


def _norm_key(key) -> str:
    return re.sub(r"[^A-Z]", "", str(key).upper())


def _alnum(text) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def _words(text) -> list:
    return str(text or "").split()


def _raw_keys(rows: list) -> Optional[dict]:
    keys = set()
    for inv in rows:
        keys |= set((inv.get("_raw_row") or {}).keys())
    by_norm = {}
    for k in keys:
        if isinstance(k, str):
            by_norm.setdefault(_norm_key(k), []).append(k)
    found = {}
    for name, norm in (("merged", MERGED_KEY), ("Charged", "CHARGED"), ("Paid", "PAID"), ("Unalloc.", "UNALLOC")):
        if len(by_norm.get(norm, [])) != 1:
            return None
        found[name] = by_norm[norm][0]
    if "DUE" in by_norm:
        return None
    return found


def _header(line: dict) -> Optional[dict]:
    """{column: right edge, "description": left edge} from a header printing the Autoly ledger columns
    as separate words, in order."""
    words = {w["text"]: w for w in line["words"]}
    if not all(name in words for name in _COLUMNS + ("Description",)):
        return None
    edges = [words[name] for name in _COLUMNS + ("Description",)]
    if any(a["x1"] >= b["x0"] for a, b in zip(edges, edges[1:])):
        return None
    out = {name: words[name]["x1"] for name in _COLUMNS}
    out["description"] = words["Description"]["x0"]
    return out


def _column(x1: float, header: dict) -> Optional[str]:
    distances = sorted((abs(x1 - header[name]), name) for name in _COLUMNS)
    if distances[0][0] > _SNAP or distances[1][0] - distances[0][0] < _MARGIN:
        return None
    return distances[0][1]


def read_ledger(pdf_path: str) -> dict:
    """{"lines": [{"page", "date", "tokens", "cells": {column: value}, "description": [words]}],
    "totals": {column: value} or None, "problem": str or None}, from pdf_row_match's text-layer / OCR
    read of the PDF."""
    from src.validation import pdf_row_match

    def problem(text):
        return {"lines": [], "totals": None, "problem": text}

    try:
        pages = pdf_row_match.read_pdf_lines(pdf_path)
    except pdf_row_match.NotVerified as e:
        return problem(f"PDF not read: {e}")
    header, lines, totals = None, [], None
    for page in pages:
        for line in page["lines"]:
            found = _header(line)
            if found:
                header = found
                continue
            if header is None or not line["words"]:
                continue
            first = line["words"][0]["text"]
            is_totals = first.lower() == "totals"
            if not (_DATE_RE.match(first) or is_totals):
                continue
            cells, tokens, description = {}, [], []
            for w in line["words"][1:]:
                if w["x0"] >= header["description"] - 1:
                    description.append(w["text"])
                    continue
                value = pdf_row_match.parse_money(w["text"]) if re.search(r"\d\.\d{2}", w["text"]) else None
                if value is None:
                    tokens.append(w["text"])
                    continue
                column = _column(w["x1"], header)
                if column is None or column in cells:
                    return problem(f"p{page['page']}: amount {w['text']} can't be placed in one column: {line['text']!r}")
                cells[column] = round(value, 2)
            if is_totals:
                totals = cells
                continue
            lines.append({"page": page["page"], "date": first, "tokens": tokens, "cells": cells,
                          "description": description, "text": line["text"]})
    if header is None:
        return problem("no printed Charged / Paid / Unalloc. / Due / Description header (Due as its own word)")
    if not lines:
        return problem("no dated ledger lines found")
    return {"lines": lines, "totals": totals, "problem": None}


def _same(extracted, printed) -> bool:
    if extracted is None:
        return printed is None
    return printed is not None and abs(round(float(extracted), 2) - printed) < _CENT


def plan_due_column_corrections(invoices: list, pdf_path: Optional[str], printed: Optional[float]) -> dict:
    """{"applicable": bool, "reason": str, "corrections": [...], "pdf_total": float or None}. Reads only."""
    def refuse(reason, **extra):
        return {"applicable": False, "reason": reason, "corrections": [], **extra}

    rows = [inv for inv in invoices or [] if not inv.get("informational")]
    keys = _raw_keys(rows)
    if keys is None:
        return refuse(NOT_APPLICABLE)
    if any(inv.get("amount_due") is not None for inv in rows):
        return refuse("a row's Due field already holds a value")
    leading = {}
    for index, inv in enumerate(rows):
        m = _LEADING_RE.match(str((inv.get("_raw_row") or {}).get(keys["merged"]) or ""))
        if m:
            leading[index] = (round(float(m.group(1).replace(",", "")), 2), m.group(2).strip())
    if not leading:
        return refuse("no Due Description cell starts with an amount")
    if not pdf_path or not os.path.exists(pdf_path):
        return refuse("no PDF")
    if printed is None:
        return refuse("no printed total")
    ledger = read_ledger(pdf_path)
    if ledger["problem"]:
        return refuse(ledger["problem"])
    lines = ledger["lines"]
    pdf_due = round(sum(l["cells"].get("Due", 0) for l in lines), 2)
    pdf_unalloc = round(sum(abs(l["cells"].get("Unalloc.", 0)) for l in lines), 2)
    pdf_total = round(pdf_due - pdf_unalloc, 2)
    if abs(pdf_total - printed) > _CENT:
        return refuse(f"the PDF's Due {pdf_due:,.2f} - Unalloc. {pdf_unalloc:,.2f} = {pdf_total:,.2f}, "
                      f"not the printed {printed:,.2f}", pdf_total=pdf_total)
    totals = ledger["totals"]
    if totals and any(abs(totals[c] - s) > _CENT for c, s in (("Due", pdf_due), ("Unalloc.", pdf_unalloc)) if c in totals):
        return refuse(f"the printed Totals line {totals} does not equal the lines' columns", pdf_total=pdf_total)

    claimed, pairs = {}, []
    for index, inv in enumerate(rows):
        number = inv.get("row_number") or index + 1
        label = f"row {number} ({inv.get('invoice_number')})"
        ref, date = _alnum(inv.get("invoice_number")), str(inv.get("invoice_date") or "").strip()
        if not ref or not date:
            return refuse(f"{label} has no reference or date", pdf_total=pdf_total)
        candidates = [i for i, l in enumerate(lines) if l["date"] == date and ref in {_alnum(t) for t in l["tokens"]}]
        if len(candidates) != 1:
            return refuse(f"{label} {date}: matches {len(candidates)} printed lines, not exactly one", pdf_total=pdf_total)
        if candidates[0] in claimed:
            return refuse(f"{label} and row {claimed[candidates[0]]} claim the same printed line", pdf_total=pdf_total)
        claimed[candidates[0]] = number
        pairs.append((index, inv, lines[candidates[0]]))
    if len(claimed) != len(lines):
        return refuse(f"{len(lines) - len(claimed)} printed line(s) match no extracted row", pdf_total=pdf_total)

    corrections, changes = [], []
    for index, inv, line in pairs:
        label = f"row {inv.get('row_number') or index + 1} ({inv.get('invoice_number')})"
        raw = inv.get("_raw_row") or {}
        for column in ("Charged", "Paid", "Unalloc."):
            if not _same(raw.get(keys[column]), line["cells"].get(column)):
                return refuse(f"{label}: extracted {column} {raw.get(keys[column])}, the PDF prints "
                              f"{line['cells'].get(column)}", pdf_total=pdf_total)
        due = line["cells"].get("Due")
        if index not in leading:
            if due is not None:
                return refuse(f"{label}: the PDF prints Due {due:,.2f} but the row has no Due amount", pdf_total=pdf_total)
            continue
        amount, text = leading[index]
        if due is None or abs(amount - due) > _CENT:
            return refuse(f"{label}: the description starts with {amount:,.2f}, the PDF's Due cell is {due}", pdf_total=pdf_total)
        if _words(text) != line["description"]:
            return refuse(f"{label}: the rest of the cell {text!r} is not the printed description "
                          f"{' '.join(line['description'])!r}", pdf_total=pdf_total)
        charged = raw.get(keys["Charged"])
        if charged in (None, 0) or amount * charged < 0 or abs(amount) > abs(charged) + _CENT:
            return refuse(f"{label}: Due {amount:,.2f} does not fit its Charged {charged}", pdf_total=pdf_total)
        corrections.append({"row_number": inv.get("row_number"), "invoice_number": inv.get("invoice_number"),
                            "date": line["date"], "change": "due_from_description", "field": "Due",
                            "from": raw.get(keys["merged"]), "extracted_field": "Due Description",
                            "extracted_value": amount, "printed_value": due, "amount": due,
                            "description": text, "page": line["page"]})
        changes.append((inv, due, text))
    return {"applicable": True, "reason": "", "corrections": corrections, "pdf_total": pdf_total,
            "merged_key": keys["merged"], "_changes": changes}


def apply_due_column_corrections(plan: dict) -> int:
    """Sets each planned row's amount_due and splits its raw cell, in place. Returns the rows changed."""
    for inv, due, text in plan["_changes"]:
        inv["amount_due"] = due
        raw = inv.get("_raw_row")
        if isinstance(raw, dict):
            raw[plan["merged_key"]] = text
            raw["Due"] = due
    return len(plan["_changes"])
