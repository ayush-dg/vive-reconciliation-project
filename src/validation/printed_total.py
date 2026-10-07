"""
printed_total.py

Reads a statement's printed total from the PDF's text (its text layer, or
OCR text for a scan -- see ocr_text.py) when the extraction itself returned
none (2026-10-07). The Arithmetic Validation Gate then compares it with the
extracted rows exactly as it would a model-reported total: nothing here
passes a statement, it only supplies the printed figure to check against.

Strict on purpose -- a wrong figure must not slip in:
  - only lines carrying a total label ("PLEASE PAY THIS AMOUNT", "Total
    due", "Balance due", "Amount due", "New balance") count, and the value
    must be printed on that same line;
  - zero values are ignored (aging buckets and "STATUS 0.00" sit on the
    same lines as the real figure);
  - every non-zero value on every labelled line must agree on ONE amount --
    two different labelled amounts (e.g. a group total and a store total)
    means no printed total is returned at all.

Labels are matched with everything but letters removed, so letter-spaced
headers ("T H IS A M O U N T") match too, and "THIS AMOUNT" counts on its
own when "PLEASE PAY" is printed on the line above. Seen on the
Collex/Clinton Honda CDK layout ("... PLEASE PAY" / "STATUS 0.00 4,484.09
THIS AMOUNT 4,484.09") and Fenix reprints ("Total due 3425.00" / "Balance
due 3425.00").
"""

import re
from typing import Optional

_LABELS = (
    "pleasepaythisamount", "paythisamount", "thisamount", "totalamountdue", "amountdue",
    "balancedue", "totaldue", "newbalance",
)
_MONEY_RE = re.compile(r"\(?-?\$?\s?\d{1,3}(?:,\d{3})*\.\d{2}\)?-?|\(?-?\$?\s?\d+\.\d{2}\)?-?")


def _money_values(line: str) -> list:
    values = []
    for token in _MONEY_RE.findall(line):
        t = token.strip()
        negative = t.startswith("(") or t.startswith("-") or t.endswith("-")
        try:
            value = float(re.sub(r"[()\-\s$,]", "", t))
        except ValueError:
            continue
        values.append(round(-value if negative else value, 2))
    return values


def _is_total_line(line: str) -> bool:
    letters = re.sub(r"[^a-z]", "", line.lower())
    return any(label in letters for label in _LABELS)


def find_printed_total(text: Optional[str]) -> Optional[float]:
    """The single non-zero amount printed on the text's total-labelled
    lines, or None when there is no such line or the lines disagree."""
    amounts = set()
    for line in (text or "").splitlines():
        if _is_total_line(line):
            amounts.update(v for v in _money_values(line) if v != 0)
    return amounts.pop() if len(amounts) == 1 else None
