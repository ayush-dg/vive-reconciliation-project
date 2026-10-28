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

Never a total (2026-10-25, Faulkner -- CDK eF320 statements): a percentage
("1.50%" is a rate), and a prose line -- a sentence of terms or footer text,
recognised by having at least PROSE_MIN_WORDS lowercase words. The eF320
footer "FINANCE CHARGES will apply if the new balance is unpaid ... computed
a periodic rate of 1.50% per month" carries the words "new balance" and
supplied 1.50 as all three Faulkner statements' printed total. Measured over
every local PDF text and cached OCR text (531 texts, 282 labelled lines with
an amount): real total lines carry 0-3 lowercase words of two or more
letters, the footer 25-27. These two rules apply to the printed total only
(labelled_amounts / find_printed_total); full_match_no_total.py's safety
check still sees every amount on a labelled line.
"""

import re
from typing import Optional

_LABELS = (
    "pleasepaythisamount", "paythisamount", "thisamount", "totalamountdue", "amountdue",
    "balancedue", "totaldue", "newbalance",
)
_MONEY_RE = re.compile(r"\(?-?\$?\s?\d{1,3}(?:,\d{3})*\.\d{2}\)?-?|\(?-?\$?\s?\d+\.\d{2}\)?-?")
_PERCENT_AFTER_RE = re.compile(r"\s*%")
# Lowercase words (two or more letters) that make a line prose, not a total
# line -- see the module docstring. Letter-spaced labels ("T o t a l D u e")
# are single letters and never count.
PROSE_MIN_WORDS = 8
_LOWERCASE_WORD_RE = re.compile(r"(?<![A-Za-z])[a-z]{2,}(?![A-Za-z])")


def _money_values(line: str, skip_percentages: bool = False) -> list:
    values = []
    for match in _MONEY_RE.finditer(line):
        if skip_percentages and _PERCENT_AFTER_RE.match(line, match.end()):
            continue  # "1.50%" is a rate, not an amount
        t = match.group(0).strip()
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


# "THIS AMOUNT", letter-spaced or not ("T H IS A M O U N T").
_THIS_AMOUNT_RE = re.compile(r"T\s*H\s*I\s*S\s*A\s*M\s*O\s*U\s*N\s*T", re.IGNORECASE)


def _line_amounts(line: str, skip_percentages: bool = False) -> list:
    """The non-zero amounts a total-labelled line contributes. On a "...THIS
    AMOUNT" line only the amounts printed AFTER the label count (2026-10-19):
    the CDK layout prints the aging boxes on the same line, so with a past-due
    balance the line carries three different figures -- Bowser Klapec 1.pdf:
    "STATUS 450.00 63,380.20 | PLEASE PAY THIS AMOUNT 63,830.20" (past due,
    current, the total). If nothing is printed after the label, the whole
    line counts, as before. skip_percentages leaves out "1.50%"-style rates."""
    match = _THIS_AMOUNT_RE.search(line)
    if match:
        after = [v for v in _money_values(line[match.end():], skip_percentages) if v != 0]
        if after:
            return after
    return [v for v in _money_values(line, skip_percentages) if v != 0]


def _is_prose(line: str) -> bool:
    """A sentence of terms or footer text (PROSE_MIN_WORDS lowercase words or
    more), never a total line, whatever label words it contains."""
    return len(_LOWERCASE_WORD_RE.findall(line)) >= PROSE_MIN_WORDS


def labelled_amounts(text: Optional[str]) -> set:
    """Every non-zero amount printed on the text's total-labelled lines --
    prose lines and percentages left out (see the module docstring)."""
    amounts = set()
    for line in (text or "").splitlines():
        if _is_total_line(line) and not _is_prose(line):
            amounts.update(_line_amounts(line, skip_percentages=True))
    return amounts


def find_printed_total(text: Optional[str]) -> Optional[float]:
    """The single non-zero amount printed on the text's total-labelled
    lines (not prose, not a percentage), or None when there is no such line
    or the lines disagree."""
    amounts = labelled_amounts(text)
    return amounts.pop() if len(amounts) == 1 else None


# ---------------------------------------------------------------------------
# Bare box labels (2026-10-21, Groove / Berlin City STMT-B9D084C8)
# ---------------------------------------------------------------------------
#
# A header box labelled only "BALANCE" or "NET DUE" with its amount printed in
# the cell below (Berlin City prints BALANCE on every page and NET DUE on the
# aging line of the last). The labels above never match these, and a plain
# text read loses which value sits under which label -- so this reads the
# PDF's positioned lines (pdf_row_match.read_pdf_lines: the text layer's
# words, or Tesseract's for a scan). It is used ONLY when the text above has
# no total-labelled amount at all, so it never changes a text the labels
# above decide. A label counts only when:
#   - it stands alone: no word directly before or after it on its line
#     ("CLOSING DATE OF BALANCE", "Balance Due", "NET DUE 30 DAYS" don't);
#   - its amount is printed right after it on its line, or is the ONE amount
#     directly under it, with no amount under that again (a box holds one
#     value; a column of balances under a table header is not a total);
#   - on a scanned page whose line under the label reads no amount, one
#     focused re-read of the cell under the label (pdf_row_match._Rereader:
#     binarised, digits only) supplies it, and only if it reads exactly one
#     amount.
# Zero amounts are ignored. Every amount found must be the same, and it must
# be found in at least BOX_MIN_PLACES different places (page + label), so a
# single noisy read can never supply a total. The rows are never used.

BOX_LABELS = (("balance",), ("net", "due"))
BOX_MIN_PLACES = 2
_BOX_GAP_HEIGHTS = 1.0      # a neighbouring word closer than this many line heights joins the label
_BOX_BELOW_HEIGHTS = 4.0    # the value line starts within this many label heights below it
_BOX_CACHE: dict = {}


def _word_key(w) -> str:
    return w["text"].strip().rstrip(":").lower()


def _bare_labels(line):
    """[(label, x0, x1, top, bottom, value_word_or_None)] for every stand-alone
    box label on the line. A word whose span contains the whole label (a box
    edge OCR read as one wide word) is not a neighbour; an amount right after
    the label is its value, not a neighbour."""
    from src.validation.pdf_row_match import parse_money
    words = sorted(line["words"], key=lambda w: w["x0"])
    height = max(line["bottom"] - line["top"], 1.0)
    out = []
    for label in BOX_LABELS:
        for k in range(len(words) - len(label) + 1):
            run = words[k:k + len(label)]
            if [_word_key(w) for w in run] != list(label):
                continue
            x0, x1 = run[0]["x0"], run[-1]["x1"]
            others = [w for i, w in enumerate(words) if not k <= i < k + len(label)
                      and not (w["x0"] <= x0 and w["x1"] >= x1)]
            before = [w for w in others if w["x1"] <= x0 + 0.5 and x0 - w["x1"] < _BOX_GAP_HEIGHTS * height]
            after = [w for w in others if w["x0"] >= x1 - 0.5 and w["x0"] - x1 < _BOX_GAP_HEIGHTS * height]
            value = None
            if after and parse_money(after[0]["text"]) is not None and len(after) == 1:
                value, after = after[0], []
            if before or after:
                continue
            out.append((" ".join(label).upper(), x0, x1, min(w["top"] for w in run),
                        max(w["bottom"] for w in run), value))
    return out


def _money_under(lines, i, x0, x1, top_limit):
    """(the line index, the money words under [x0, x1]) of the FIRST line below
    line i that prints anything under [x0, x1] and starts before top_limit;
    (None, []) when that line prints no amount there, or there is no such line."""
    from src.validation.pdf_row_match import parse_money
    for j in range(i + 1, len(lines)):
        if lines[j]["top"] > top_limit:
            break
        under = [w for w in lines[j]["words"] if w["x1"] > x0 - 2 and w["x0"] < x1 + 2]
        if under:
            hits = [w for w in under if parse_money(w["text"]) is not None]
            return (j, hits) if hits else (None, [])
    return None, []


def find_box_total(pdf_path: Optional[str]) -> Optional[dict]:
    """{"amount", "places": [{"page", "label", "amount", "read"}], "unread":
    [...]} when the bare box labels agree on one non-zero amount in at least
    BOX_MIN_PLACES places, else None. Never raises."""
    if not pdf_path:
        return None
    import os
    try:
        key = (os.path.abspath(pdf_path), os.path.getmtime(pdf_path))
    except OSError:
        return None
    if key not in _BOX_CACHE:
        try:
            _BOX_CACHE[key] = _find_box_total(pdf_path)
        except Exception:
            _BOX_CACHE[key] = None
        while len(_BOX_CACHE) > 8:
            _BOX_CACHE.pop(next(iter(_BOX_CACHE)))
    return _BOX_CACHE[key]


def _find_box_total(pdf_path):
    import time
    from src.validation import pdf_row_match as prm
    try:
        pages = prm.read_pdf_lines(pdf_path)
    except prm.NotVerified:
        return None
    rereader = None
    places, unread = [], []
    for page in pages:
        lines = page["lines"]
        for i, line in enumerate(lines):
            for label, x0, x1, top, bottom, value_word in _bare_labels(line):
                height = max(bottom - top, 1.0)
                where = {"page": page["page"], "label": label}
                if value_word is not None:
                    places.append({**where, "amount": prm.parse_money(value_word["text"]), "read": "same line"})
                    continue
                j, hits = _money_under(lines, i, x0, x1, bottom + _BOX_BELOW_HEIGHTS * height)
                if hits:
                    if len(hits) != 1:
                        return None  # two amounts under one label: no single value
                    k, again = _money_under(lines, j, x0, x1, lines[j]["bottom"] + _BOX_BELOW_HEIGHTS * height)
                    if again:
                        continue  # a column of amounts under a table header, not a box
                    places.append({**where, "amount": prm.parse_money(hits[0]["text"]), "read": "printed under"})
                    continue
                if page["source"] != "ocr" or page.get("rotation"):
                    unread.append({**where, "why": "no amount under the label"})
                    continue
                rereader = rereader or prm._Rereader(pdf_path, time.monotonic() + prm.ocr_time_budget_seconds())
                width = x1 - x0
                got = rereader._ocr(page["page"], (x0 - width, bottom + 1, x1 + 1.75 * width,
                                                   bottom + 2.6 * height), "0123456789.,$-", 7) or []
                amounts = [prm.parse_money(w["text"]) for w in got]
                if len(got) == 1 and amounts[0] is not None:
                    places.append({**where, "amount": amounts[0], "read": "re-read under the label"})
                else:
                    unread.append({**where, "why": f"re-read under the label: {' '.join(w['text'] for w in got) or 'nothing'}"})
    places = [p for p in places if p["amount"] is not None and abs(p["amount"]) >= 0.005]
    amounts = {round(p["amount"], 2) for p in places}
    if len(amounts) != 1 or len({(p["page"], p["label"]) for p in places}) < BOX_MIN_PLACES:
        return None
    return {"amount": amounts.pop(), "places": places, "unread": unread}
