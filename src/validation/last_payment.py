"""
last_payment.py

Recognises an informational "LAST PAYMENT: <date> <amount>" note that the
extraction model returned as a line item WITHOUT its label -- which
claude_sonnet_client.py's own text-based check (LAST_PAYMENT_NOTE_RE on the
row's cells) therefore can't see. MAINE OXY prints the note under its item
list; on 2026-10-01 Claude returned it as a bare row (no invoice number, the
amount in an amount/aging column), so it was counted as a charge (MAINE OXY
RP 0826 and JC 093026), or -- on MAINE OXY HEW 0926 -- was only left out by
the since-fixed zero-cents fallback bug.

The PDF's text layer settles it deterministically: a row with no invoice
number whose amount is printed on a "LAST PAYMENT" line, and on no other
line of the text layer, is that note. "On no other line" is what keeps a
real payment printed inside the transaction table (which has its own line)
from ever being touched, even when it happens to be the same amount.
"""

import re
from typing import Optional

LAST_PAYMENT_LINE_RE = re.compile(r"last\s*payment", re.IGNORECASE)
_MONEY_RE = re.compile(r"-?\d{1,3}(?:,\d{3})*\.\d{2}|-?\d+\.\d{2}")

# Fields cleared on a row recognised as the note -- it stays a row (Bronze
# keeps it, see get_skip_reason()'s BERLIN HEW carve-out) but never carries
# an amount.
_AMOUNT_FIELDS = ("outstanding_amount", "amount", "charges", "credit", "credits", "amount_due")


def _amounts(line: str) -> set:
    return {round(abs(float(m.replace(",", ""))), 2) for m in _MONEY_RE.findall(line)}


def last_payment_note_amounts(pdf_text: Optional[str]) -> set:
    """Amounts printed on a "LAST PAYMENT" line and on no other line."""
    if not pdf_text:
        return set()
    on_note, elsewhere = set(), set()
    for line in pdf_text.splitlines():
        if LAST_PAYMENT_LINE_RE.search(line):
            on_note |= _amounts(line)
        else:
            elsewhere |= _amounts(line)
    return on_note - elsewhere


def mark_last_payment_notes(invoices: list, pdf_text: Optional[str]) -> int:
    """Marks (in place) every row with no invoice number whose amount is a
    last-payment note amount (see last_payment_note_amounts()) as
    informational, clearing its amount fields. Returns how many rows."""
    amounts = last_payment_note_amounts(pdf_text)
    if not amounts or not invoices:
        return 0
    marked = 0
    for inv in invoices:
        if inv.get("invoice_number") or inv.get("informational"):
            continue
        amount = inv.get("outstanding_amount") if inv.get("outstanding_amount") is not None else inv.get("credit")
        if amount is None or round(abs(amount), 2) not in amounts:
            continue
        for field in _AMOUNT_FIELDS:
            if field in inv:
                inv[field] = None
        inv["informational"] = True
        marked += 1
    return marked
