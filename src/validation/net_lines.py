"""
net_lines.py

A printed invoice-net line taken for a transaction (2026-10-21, Blaise Alexander Hyundai Mazda
STMT-36ECEA09). Reynolds-style dealer statements print, under an invoice with a charge and a credit
memo, the invoice's net on a line of its own (no date, no invoice, no reference -- the amount and the
age only), and repeat it on the remittance stub with the date and invoice ("07-23 HYW39227-1 89.08").
The client drops such a recap line only when the extraction gave it no date
(claude_sonnet_client._drop_recap_rows); when the model copies the invoice's date onto it, the line
stays a row and counts twice (Blaise: -545.46 + 634.54 = 89.08, extracted again as a row).

plan_net_line_drop() only PLANS. It refuses -- changing nothing -- unless all of this holds:
  - exactly ONE row of the statement has no invoice number, no reference and no description in its
    extracted cells (a built invoice_number that is only the client's value-based fallback copy of
    another cell, e.g. the date, does not count) and an amount equal, to the cent with its sign, to
    the net of the two or more rows directly above it that all belong to ONE invoice;
  - the PDF (text layer, or Tesseract word positions for a scan -- pdf_row_match.read_pdf_lines)
    prints exactly one line with that amount and nothing before it on the line: no date token, no
    invoice/reference token, no word at all;
  - the line directly above it prints the amount of the invoice's last row;
  - the same amount is printed again elsewhere on the PDF on a line that carries the invoice number
    (the remittance stub or recap area).
The printed total is never used. The caller (notebooks/01_document_intake.py) runs it only on a
statement that still fails the gate after every other correction, applies the plan on a copy first
and keeps it only if the whole gate then passes; then the row is removed in place and recorded in
detail["net_line_drops"] with its cells, the invoice rows it nets and the printed lines.

NET_LINE_DROP_ENABLED=false switches it off (default on).
"""

import os
from typing import Optional

ENV_FLAG = "NET_LINE_DROP_ENABLED"
NOT_APPLICABLE = "no row without invoice / reference / description equals the net of one invoice's rows above it"
_CENT = 0.005
_REF_WORDS = ("REF", "INVOICE", "INV", "DOC", "DESC")


def enabled() -> bool:
    return os.getenv(ENV_FLAG, "true").strip().lower() != "false"


def _blank(value) -> bool:
    return value is None or str(value).strip() == ""


def _ref_keys(raw: dict) -> list:
    return [k for k in raw if any(w in str(k).upper() for w in _REF_WORDS)]


def _no_reference(inv: dict) -> bool:
    """No invoice number, reference or description in the row's extracted cells."""
    raw = inv.get("_raw_row") or {}
    keys = _ref_keys(raw)
    if not keys or not all(_blank(raw[k]) for k in keys) or not _blank(inv.get("description")):
        return False
    number = inv.get("invoice_number")
    if _blank(number):
        return True
    # The client's value-based fallback copies another cell (e.g. the date) into invoice_number.
    return any(str(v).strip() == str(number).strip() for k, v in raw.items() if k not in keys)


def _refuse(reason: str) -> dict:
    return {"applicable": False, "reason": reason, "drop": None}


def _candidates(rows: list) -> list:
    from src.validation.arithmetic_gate import _row_net
    found = []
    for k, inv in enumerate(rows):
        net = round(_row_net(inv), 2)
        if inv.get("informational") or abs(net) < _CENT or not _no_reference(inv):
            continue
        group = []
        for prev in reversed(rows[:k]):
            number = prev.get("invoice_number")
            if _blank(number) or _no_reference(prev) or (group and number != group[0].get("invoice_number")):
                break
            group.append(prev)
        if len(group) >= 2 and abs(round(sum(_row_net(p) for p in group), 2) - net) < _CENT:
            found.append((k, inv, list(reversed(group)), net))
    return found


def plan_net_line_drop(invoices: list, pdf_path: Optional[str]) -> dict:
    """{"applicable", "reason", "drop"} -- see the module docstring."""
    from src.validation import pdf_row_match as prm
    from src.validation.arithmetic_gate import _row_net
    rows = [inv for inv in invoices if not inv.get("informational")]
    found = _candidates(rows)
    if not found:
        return _refuse(NOT_APPLICABLE)
    if len(found) > 1:
        return _refuse(f"{len(found)} rows look like invoice-net lines; only one may be dropped")
    k, inv, group, net = found[0]
    invoice = group[0].get("invoice_number")
    if not pdf_path:
        return _refuse("no PDF to check the net line against")
    try:
        pages = prm.read_pdf_lines(pdf_path)
    except prm.NotVerified as e:
        return _refuse(f"PDF not verified: {e}")
    except Exception as e:
        return _refuse(f"PDF unreadable ({type(e).__name__})")
    want_invoice = prm.norm_invoice(invoice)
    last_amount = round(_row_net(group[-1]), 2)

    def amount_words(line):
        return [w for w in line["words"] if (v := prm.parse_money(w["text"])) is not None and abs(v - net) < _CENT]

    net_lines, stubs = [], []
    for page in pages:
        lines = page["lines"]
        for i, line in enumerate(lines):
            for w in amount_words(line):
                before = [x for x in line["words"] if x["x1"] <= w["x0"] + 0.5 and x is not w]
                if not before:
                    net_lines.append((page, i, line, w))
                elif any(prm.norm_invoice(x["text"]) == want_invoice for x in line["words"] if x["x0"] < w["x0"]):
                    stubs.append((page, line, w))
    if len(net_lines) != 1:
        return _refuse(f"the PDF prints {len(net_lines)} lines with {net:,.2f} and nothing before it (need exactly one)")
    page, i, line, word = net_lines[0]
    above = page["lines"][i - 1] if i > 0 else None
    if above is None or not any((v := prm.parse_money(x["text"])) is not None and abs(v - last_amount) < _CENT
                                for x in above["words"]):
        return _refuse(f"the line above the printed {net:,.2f} does not print the invoice's last row {last_amount:,.2f}")
    if not stubs:
        return _refuse(f"{net:,.2f} is not printed again with invoice {invoice} (remittance stub or recap)")
    stub_page, stub_line, _ = stubs[0]
    raw = dict(inv.get("_raw_row") or {})
    raw.pop("confidence", None)
    drop = {"row_number": inv.get("row_number"), "position": invoices.index(inv) + 1, "amount": net,
            "date_extracted": inv.get("invoice_date"), "cells": raw, "invoice_number": invoice,
            "nets_rows": [{"row_number": g.get("row_number"), "amount": round(_row_net(g), 2),
                           "date": g.get("invoice_date")} for g in group],
            "page": page["page"], "printed_line": line["text"][:100],
            "stub_page": stub_page["page"], "stub_line": stub_line["text"][:100],
            "_row": inv}
    return {"applicable": True, "reason": "", "drop": drop}


def apply_net_line_drop(invoices: list, plan: dict) -> int:
    """Removes the planned row from invoices (in place). Returns 1, or 0 when it is not there."""
    row = plan["drop"]["_row"]
    for k, inv in enumerate(invoices):
        if inv is row:
            del invoices[k]
            return 1
    return 0


def record(plan: dict) -> dict:
    """The drop as stored in the validation detail (no object references)."""
    return {k: v for k, v in plan["drop"].items() if not k.startswith("_")}
