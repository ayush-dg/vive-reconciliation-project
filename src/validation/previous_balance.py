"""
previous_balance.py

Resolves a statement's printed previous balance (balance forward) for the
Arithmetic Validation Gate's statement_equation / running_balance fallbacks
(src/validation/arithmetic_gate.py). The extraction prompt has always told
the model to drop the balance-forward line from the rows, so before
2026-10-06 that figure was simply lost and every "previous balance +
activity = new balance" statement failed validation (29 of the Oct 1
failures -- see scratchpad/oct1_report/oct1_root_cause_analysis.md).

Two sources, and the rule that keeps a fallback pass honest:
  - the model's own `previous_balance` + `previous_balance_label`
    (claude_sonnet_client.py), and
  - a deterministic read of the PDF's text layer: a line carrying a
    balance-forward label and a money value.
When the PDF has a text layer, a model value is accepted ONLY if that same
value is printed on a labelled balance-forward line; otherwise it is
rejected (never "trusted"). When there is no text layer (a scan), the model
value is accepted only if its printed label is a balance-forward label
(is_balance_forward_label()) -- not a date or another field's name. When the
model gave nothing, a single unambiguous labelled value in the text layer is
used.

A scan's model value that came with some other label -- typically only the
date printed on an unlabelled opening line (Northeast Coffee: "08/01/26 ...
80.40") -- is never a previous balance, so statement_equation can't use it.
It is returned as "chain_opening": the opening figure the running_balance
check may start from, where it only passes if every row's printed balance
chains from it to the printed total (2026-10-06).
"""

import re
from typing import Optional

# Matched against the line with all whitespace removed and lower-cased, so
# letter-spaced headers ("PR E V IO U S B A LA N C E") still match.
_LABELS = (
    "balanceforward", "balancefwd", "balancebfwd", "bfwd", "previousbalance", "prevbalance",
    "prevbal", "prvbalance", "priorbalance", "beg.balance", "begbalance", "beginningbalance",
    "balancebroughtforward", "broughtforward", "openingbalance", "lastbalance",
)
# A model label is compared with punctuation removed as well, so a few more
# abbreviations are listed for it ("BAL. FWD", "Previous Statement Balance").
_MODEL_LABEL_EXTRAS = (
    "balfwd", "balforward", "previousstatementbalance", "priorstatementbalance",
    "laststatementbalance", "beginbal", "openingbal",
)
_MONEY_RE = re.compile(r"\(?-?\$?\s?\d{1,3}(?:,\d{3})*\.\d{2}\)?-?|\(?-?\$?\s?\d+\.\d{2}\)?-?")
# Below this many letters/digits a PDF is treated as having no usable text
# layer (scans typically carry a stray page number or nothing at all).
_MIN_TEXT_LAYER_CHARS = 200


def _money_values(line: str) -> list:
    values = []
    for token in _MONEY_RE.findall(line):
        t = token.strip()
        negative = t.startswith("(") or t.startswith("-") or t.endswith("-")
        digits = re.sub(r"[()\-\s$,]", "", t)
        try:
            value = float(digits)
        except ValueError:
            continue
        values.append(round(-value if negative else value, 2))
    return values


def is_balance_forward_label(label: Optional[str]) -> bool:
    """True when label names a balance forward ("Balance Forward", "Previous
    Balance", "BFWD", "Beg. Balance", ...) -- not a date, an amount, or
    another field ("PREV SERV CHARGES", "Total Due", "Balance")."""
    squashed = re.sub(r"[\s.:\-_/]", "", (label or "").lower())
    return any(l.replace(".", "") in squashed for l in _LABELS + _MODEL_LABEL_EXTRAS)


def has_text_layer(pdf_text: Optional[str]) -> bool:
    return bool(pdf_text) and len(re.findall(r"[A-Za-z0-9]", pdf_text)) >= _MIN_TEXT_LAYER_CHARS


_VALUE_AFTER_LABEL_RE = re.compile(r"^[:$]*(\(?-?\$?\d{1,3}(?:,\d{3})*\.\d{2}\)?-?|\(?-?\$?\d+\.\d{2}\)?-?)")


def find_labelled_previous_balances(pdf_text: Optional[str]) -> list:
    """Every money value printed IMMEDIATELY after a balance-forward label
    (only spaces, ':' or '$' in between), in document order. Duplicates are
    kept -- many layouts print the figure twice on one line, e.g. LKQ's
    "Balance forward $3,214.50 $3,214.50". Requiring the value to follow the
    label directly is what keeps a column-header line such as Sullivan's
    "PREV BAL PAYMENTS & ADJ ... AMOUNT DUE 725.00" from contributing its
    amount due."""
    found = []
    for line in (pdf_text or "").splitlines():
        squashed = re.sub(r"\s+", "", line).lower()
        # Finance-charge boilerplate ("... ANNUAL PERCENTAGE RATE of 18.00%
        # ... from the previous balance") names the label but its number is
        # a rate, not a balance.
        if "%" in line or "financecharge" in squashed or "percentagerate" in squashed:
            continue
        for label in sorted(_LABELS, key=len, reverse=True):
            start = 0
            while True:
                at = squashed.find(label, start)
                if at == -1:
                    break
                start = at + len(label)
                match = _VALUE_AFTER_LABEL_RE.match(squashed[start:])
                if match:
                    found.extend(_money_values(match.group(1)))
            if label in squashed:
                break  # the longest label present on this line wins
    return found


def resolve_previous_balance(model_value, model_label: Optional[str], pdf_text: Optional[str],
                             text_source: str = "text_layer") -> dict:
    """Returns {"value": float|None, "source": str|None, "label": str|None}.

    source is one of "text_layer" (value read from the PDF text),
    "model+text_layer" (model value corroborated by the text layer),
    "model_label_only" (scan: model value with its printed balance-forward
    label), or "rejected: ..." when a model value could not be accepted.
    A rejected scan value that came with a non-balance-forward label is
    also returned as "chain_opening" (running_balance check only).

    text_source="ocr" (2026-10-07): pdf_text is a scan's OCR text
    (ocr_text.py), read with exactly the same labelled-line rules; the
    sources are then reported as "ocr" / "model+ocr" instead."""
    value = None
    if model_value is not None:
        try:
            value = round(float(model_value), 2)
        except (TypeError, ValueError):
            value = None
    label = (model_label or "").strip() or None
    text_layer = has_text_layer(pdf_text)
    candidates = find_labelled_previous_balances(pdf_text) if text_layer else []

    if value is not None:
        if text_layer:
            if any(abs(c - value) < 0.005 for c in candidates):
                return {"value": value, "source": f"model+{text_source}", "label": label}
            return {"value": None, "source": f"rejected: not on a labelled line in the {text_source.replace('_', ' ')}",
                    "label": label}
        if label and is_balance_forward_label(label):
            return {"value": value, "source": "model_label_only", "label": label}
        if label:
            return {"value": None, "source": "rejected: label is not a balance-forward label", "label": label,
                    "chain_opening": value}
        return {"value": None, "source": "rejected: no printed label", "label": None}

    distinct = sorted(set(candidates))
    if len(distinct) == 1:
        return {"value": distinct[0], "source": text_source, "label": None}
    return {"value": None, "source": None, "label": None}
