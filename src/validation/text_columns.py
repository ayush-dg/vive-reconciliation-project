"""
text_columns.py

Text-layer column correction (2026-10-19). On a CDK statement with a text layer
(headers PURCHASES / PAYMENTS & CREDITS / BALANCE) the side every transaction is
printed on -- charge or credit -- can be read from the words' x-positions. The
model sometimes puts a payment under PURCHASES or swaps a charge and a credit
(Downeast Toyota, Oct 1: STMT-9D183149, -656EF295, -4E6F15BD, -89B2FD3E -- in all
four the PDF's own columns reproduce the printed total to the cent).

plan_text_column_corrections() only PLANS: it reads the PDF, matches every
extracted row to exactly one printed transaction line (reference + date +
amount, identical keys paired one-to-one in order) and lists the rows whose side
differs. It refuses -- returns applicable False with a reason, changing nothing
-- for a scan or a PDF without the headers, an extraction whose columns are not
PURCHASES / PAYMENTS & CREDITS, any amount that cannot be placed in one column,
any row or line left over, or a PDF whose column totals do not equal the printed
total exactly. The caller (notebooks/01_document_intake.py
apply_arithmetic_validation) applies a plan only to a statement that fails the
gate, and keeps it only if the corrected rows then pass.

apply_text_column_corrections() moves each listed row's amount between the
charge fields (outstanding_amount, amount, charges, the PURCHASES column of
_raw_row) and the credit fields (credit, credits, the PAYMENTS & CREDITS column)
in place, so Bronze, Silver and matching all see the corrected row.

Row correction from the printed line (C2, 2026-10-20) -- plan_text_row_corrections() /
apply_text_row_corrections(), tried only after the column correction above refuses or does not
pass. It reads other column header sets too -- CHARGES / CREDITS (or PYMTS/CR) [/ BALANCE] and a
single signed AMOUNT column -- and besides moving a row to the side the PDF prints it on, it may
take a row's amount from its own printed line when the extracted amount is missing or differs
(Goldstein STMT-33A495CD, RH Long STMT-74B91C07, NYE STMT-4AD32710 / -E2B6D395). Every row must
match exactly one printed transaction line by reference + date (plus its other printed text, e.g.
PO#/MEMO, where the reference repeats) and every printed transaction line must be claimed by
exactly one row; each line prints exactly one amount in an amount column, and that amount (its
own words, its own column and sign) is the only value ever written. Lines that do not start with
a date -- invoice subtotals, balances, totals -- are never transaction lines. An extracted amount
that differs from its line is replaced only if the extracted value is itself printed somewhere on
the PDF (the model took another printed number); an amount printed nowhere refuses. The PDF's
columns must total the printed total exactly. Anything else refuses and changes nothing.

TEXT_COLUMN_CORRECTION_ENABLED=false switches both corrections off (default on).
"""

import os
import re
from typing import Optional

ENV_FLAG = "TEXT_COLUMN_CORRECTION_ENABLED"
CHARGE, CREDIT = "charge", "credit"
_DATE_RE = re.compile(r"^\d{2}[A-Z]{3}\d{2}$")
_MONEY_RE = re.compile(r"^-?[\d,]*\d\.\d{2}-?$")
_BOUNDARY_MARGIN = 3.0   # pt: an amount whose right edge is this close to a column boundary is ambiguous
_LINE_TOLERANCE = 2.5    # pt: words whose tops differ by less are on one printed line
_CENT = 0.005


def enabled() -> bool:
    return os.getenv(ENV_FLAG, "true").strip().lower() != "false"


def _money(text: str) -> Optional[float]:
    if not _MONEY_RE.match(text):
        return None
    negative = text.startswith("-") or text.endswith("-")
    value = float(text.strip("-").replace(",", ""))
    return -value if negative else value


def _norm_ref(ref) -> str:
    return re.sub(r"\s+", "", str(ref or "")).upper()


def _group_lines(words: list) -> list:
    lines = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(w["top"] - lines[-1][0]["top"]) < _LINE_TOLERANCE:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _header(line: list) -> Optional[dict]:
    """Column geometry from a header line printing PURCHASES, PAYMENTS (& CREDITS) and BALANCE."""
    by_text = {}
    for w in line:
        by_text.setdefault(w["text"].upper(), w)
    if not {"PURCHASES", "PAYMENTS", "BALANCE"} <= set(by_text):
        return None
    purchases, payments, balance = by_text["PURCHASES"], by_text["PAYMENTS"], by_text["BALANCE"]
    payments_right = max([payments["x1"]] + [w["x1"] for w in line
                                            if w["text"] in ("&", "CREDITS") and payments["x0"] < w["x0"] < balance["x0"]])
    if not purchases["x1"] < payments["x0"] < payments_right < balance["x0"]:
        return None
    return {"left": purchases["x0"] - 60,                              # an amount must end right of here
            "b1": (purchases["x1"] + payments["x0"]) / 2,            # PURCHASES | PAYMENTS & CREDITS
            "b2": (payments_right + balance["x0"]) / 2,              # PAYMENTS & CREDITS | BALANCE
            "stub": balance["x1"] + 20}                              # right of here: remittance stub, ignored


def _column(x1: float, geometry: dict) -> Optional[str]:
    """CHARGE / CREDIT / "balance" / "stub" for an amount ending at x1; None if ambiguous."""
    if x1 < geometry["left"]:
        return None
    for boundary in (geometry["b1"], geometry["b2"]):
        if abs(x1 - boundary) < _BOUNDARY_MARGIN:
            return None
    if x1 <= geometry["b1"]:
        return CHARGE
    if x1 <= geometry["b2"]:
        return CREDIT
    return "balance" if x1 <= geometry["stub"] else "stub"


def read_pdf_transactions(pdf_path: str) -> dict:
    """{"lines": [{"page", "date", "ref", "side", "amount", "text"}], "problem": str or None}.
    "problem" set = the PDF can't be used (no text layer, no header, an ambiguous line)."""
    import pdfplumber

    lines, geometry, saw_text = [], None, False
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            words = page.extract_words()
            saw_text = saw_text or bool(words)
            for line in _group_lines(words):
                found = _header(line)
                if found:
                    geometry = found
                    continue
                if not _DATE_RE.match(line[0]["text"]):
                    continue
                text = " ".join(w["text"] for w in line)
                if geometry is None:
                    return {"lines": [], "problem": f"p{page_number}: transaction line before any column header: {text!r}"}
                ref = next((w["text"] for w in line[1:] if _money(w["text"]) is None
                            and not (w["text"].isdigit() and len(w["text"]) <= 3)), None)
                sides = []
                for w in line[1:]:
                    value = _money(w["text"])
                    if value is None:
                        continue
                    column = _column(w["x1"], geometry)
                    if column is None:
                        return {"lines": [], "problem": f"p{page_number}: amount {w['text']} can't be placed in one column: {text!r}"}
                    if column in (CHARGE, CREDIT):
                        sides.append((column, value))
                if len(sides) != 1 or ref is None:
                    return {"lines": [], "problem": f"p{page_number}: line without exactly one charge/credit amount and a reference: {text!r}"}
                side, value = sides[0]
                lines.append({"page": page_number, "date": line[0]["text"], "ref": ref, "side": side,
                              "amount": round(abs(value), 2), "signed": value, "text": text})
    if not saw_text:
        return {"lines": [], "problem": "no text layer (scan)"}
    if geometry is None:
        return {"lines": [], "problem": "no PURCHASES / PAYMENTS & CREDITS / BALANCE header"}
    if not lines:
        return {"lines": [], "problem": "no transaction lines found"}
    return {"lines": lines, "problem": None}


def _raw_columns(invoices: list) -> Optional[tuple]:
    """The extraction's own raw column names for PURCHASES and PAYMENTS & CREDITS."""
    keys = set()
    for inv in invoices:
        keys |= set((inv.get("_raw_row") or {}).keys())
    norm = {re.sub(r"[^A-Z]", "", k.upper()): k for k in keys if isinstance(k, str)}
    purchases, payments = norm.get("PURCHASES"), norm.get("PAYMENTSCREDITS")
    return (purchases, payments) if purchases and payments else None


def _row_side(inv: dict) -> Optional[tuple]:
    credit = inv.get("credit")
    charge = inv.get("outstanding_amount")
    if credit and not charge:
        return CREDIT, round(abs(credit), 2)
    if charge and not credit and charge > 0:
        return CHARGE, round(charge, 2)
    return None


def plan_text_column_corrections(invoices: list, pdf_path: Optional[str], printed: Optional[float]) -> dict:
    """{"applicable": bool, "reason": str, "corrections": [...], "pdf_total": float or None}. Reads only."""
    def refuse(reason, **extra):
        return {"applicable": False, "reason": reason, "corrections": [], **extra}

    if not pdf_path or not os.path.exists(pdf_path):
        return refuse("no PDF")
    if printed is None:
        return refuse("no printed total")
    rows = [inv for inv in invoices or [] if not inv.get("informational")]
    columns = _raw_columns(rows)
    if columns is None:
        return refuse("the extraction has no PURCHASES / PAYMENTS & CREDITS columns")
    try:
        pdf = read_pdf_transactions(pdf_path)
    except Exception as e:   # an unreadable PDF never changes anything
        return refuse(f"PDF not readable ({type(e).__name__})")
    if pdf["problem"]:
        return refuse(pdf["problem"])
    lines = pdf["lines"]
    pdf_total = round(sum(l["signed"] if l["side"] == CHARGE else -l["amount"] for l in lines), 2)
    if abs(pdf_total - printed) > _CENT:
        return refuse(f"the PDF's columns total {pdf_total:,.2f}, not the printed {printed:,.2f}", pdf_total=pdf_total)

    # One-to-one by (reference, date, amount). Within one key, a row first takes a printed line on its
    # own side (so two identical lines printed once as a charge and once as a credit are never "swapped"
    # -- STMT-656EF295 620230 0.02 / 0.02); rows left over then take the remaining lines in order.
    line_groups, row_groups = {}, {}
    for line in lines:
        line_groups.setdefault((_norm_ref(line["ref"]), line["date"], line["amount"]), []).append(line)
    for index, inv in enumerate(rows):
        side = _row_side(inv)
        if side is None:
            return refuse(f"row {inv.get('row_number') or index + 1} ({inv.get('invoice_number')}) has no single "
                          f"charge or credit amount", pdf_total=pdf_total)
        raw = inv.get("_raw_row") or {}
        key = (_norm_ref(inv.get("invoice_number")), str(raw.get("DATE") or inv.get("invoice_date") or ""), side[1])
        row_groups.setdefault(key, []).append((inv, side[0]))
    pairs = []
    for key, members in row_groups.items():
        free = list(line_groups.get(key) or [])
        if len(members) != len(free):
            inv = members[0][0]
            return refuse(f"{inv.get('invoice_number')} {key[1]} {key[2]:,.2f}: {len(members)} extracted row(s), "
                          f"{len(free)} printed line(s)", pdf_total=pdf_total)
        waiting = []
        for inv, side in members:
            same = next((line for line in free if line["side"] == side), None)
            if same is None:
                waiting.append((inv, side))
            else:
                free.remove(same)
                pairs.append((inv, side, same))
        pairs += [(inv, side, line) for (inv, side), line in zip(waiting, free)]
    left = sum(len(group) for key, group in line_groups.items() if key not in row_groups)
    if left:
        return refuse(f"{left} printed line(s) match no extracted row", pdf_total=pdf_total)
    pairs.sort(key=lambda p: rows.index(p[0]))

    corrections = [{"row_number": inv.get("row_number"), "invoice_number": inv.get("invoice_number"),
                    "date": line["date"], "amount": line["amount"], "from": side, "to": line["side"],
                    "page": line["page"]}
                   for inv, side, line in pairs if side != line["side"]]
    if not corrections:
        return refuse("the extraction's columns already agree with the PDF", pdf_total=pdf_total)
    return {"applicable": True, "reason": "", "corrections": corrections, "pdf_total": pdf_total,
            "columns": list(columns), "_pairs": [(inv, line["side"]) for inv, side, line in pairs if side != line["side"]]}


def apply_text_column_corrections(plan: dict) -> int:
    """Moves each planned row to its printed side, in place. Returns the number of rows moved."""
    purchases, payments = plan["columns"]
    for inv, to_side in plan["_pairs"]:
        raw = inv.get("_raw_row")
        if to_side == CREDIT:
            value = round(abs(inv.get("outstanding_amount") or 0), 2)
            for key in ("outstanding_amount", "amount", "charges"):
                inv[key] = None
            inv["credit"] = inv["credits"] = value
            if isinstance(raw, dict):
                raw[purchases], raw[payments] = None, value
        else:
            value = round(abs(inv.get("credit") or 0), 2)
            for key in ("credit", "credits"):
                inv[key] = None
            inv["outstanding_amount"] = inv["amount"] = inv["charges"] = value
            if isinstance(raw, dict):
                raw[payments], raw[purchases] = None, value
    return len(plan["_pairs"])


# ---------------------------------------------------------------------------------------------------
# C2: row correction from the printed line (2026-10-20)
# ---------------------------------------------------------------------------------------------------

AMOUNT = "amount"            # a single signed AMOUNT column (credits printed negative)
BALANCE = "balance"
_C2_DATE_RE = re.compile(r"^(\d{2}[A-Z]{3}\d{2}|\d{1,2}/\d{1,2}/(\d{2}|\d{4})|\d{2}-\d{2}(-(\d{2}|\d{4}))?)$")
_C2_MONEY_RE = re.compile(r"^-?\$?-?[\d,]*\d\.\d{2}-?$")
_COLUMN_REACH = 20.0         # pt: an amount's right edge must be this close to its header's right edge
_COLUMN_MARGIN = 6.0         # pt: ...and this much closer to it than to any other header
_CHARGE_LABELS = {"PURCHASES", "CHARGES"}
_CREDIT_LABELS = {"CREDITS", "PYMTS/CR", "PAYMENTS"}
_RAW_KEYS = {CHARGE: {"PURCHASES", "CHARGES"}, CREDIT: {"PAYMENTSCREDITS", "CREDITS", "PYMTSCR"},
             AMOUNT: {"AMOUNT"}}


def _c2_money(text: str) -> Optional[float]:
    if not _C2_MONEY_RE.match(text):
        return None
    negative = "-" in text
    value = float(text.replace("-", "").replace("$", "").replace(",", ""))
    return -value if negative else value


def _c2_header(line: list) -> Optional[dict]:
    """Amount-column geometry from a header line. Two-column layout: a charge label (PURCHASES /
    CHARGES) left of a credit label (PAYMENTS & CREDITS / CREDITS / PYMTS/CR). Single-column layout:
    AMOUNT with DATE and INVOICE or REFERENCE to its left (never the footer's "PAY THIS AMOUNT")."""
    upper = [(w["text"].upper(), w) for w in line]
    labels = {t for t, _ in upper}
    charge = next((w for t, w in upper if t in _CHARGE_LABELS), None)
    credit = next((w for t, w in upper if t in _CREDIT_LABELS), None)
    if charge and credit:
        if not charge["x1"] < credit["x0"]:
            return None
        credit_right = max([credit["x1"]] + [w["x1"] for t, w in upper if t in ("&", "CREDITS")
                                             and credit["x0"] <= w["x0"] < credit["x0"] + 80])
        columns = [(CHARGE, charge["x1"]), (CREDIT, credit_right)]
        layout, first_amount = "charge_credit", charge
    else:
        amount = next((w for t, w in upper if t == "AMOUNT"), None)
        if amount is None or "THIS" in labels:
            return None
        left_labels = {t for t, w in upper if w["x1"] < amount["x0"]}
        if "DATE" not in left_labels or not left_labels & {"INVOICE", "REFERENCE"}:
            return None
        columns = [(AMOUNT, amount["x1"])]
        layout, first_amount = "amount", amount
    columns += [(BALANCE, w["x1"]) for t, w in upper if t == "BALANCE" and w["x0"] > first_amount["x1"]]
    others = [w["x1"] for t, w in upper if w["x0"] > first_amount["x1"]
              and t not in _CHARGE_LABELS | _CREDIT_LABELS | {"&", "AMOUNT", "BALANCE"}]
    return {"layout": layout, "columns": columns, "others": others,
            "left": first_amount["x0"] - 40,      # a transaction line's date ends left of here
            "text_right": first_amount["x0"],     # its reference words (and PO#/MEMO...) end left of here
            "right": max([c[1] for c in columns] + others) + _COLUMN_REACH}


def _c2_column(x1: float, geometry: dict) -> Optional[str]:
    """The column an amount ending at x1 belongs to; "stub" right of every header; None if ambiguous."""
    if x1 > geometry["right"]:
        return "stub"
    edges = sorted([(abs(x1 - edge), kind) for kind, edge in geometry["columns"]] +
                   [(abs(x1 - edge), "other") for edge in geometry["others"]])
    nearest = edges[0]
    if nearest[0] > _COLUMN_REACH or nearest[1] == "other":
        return None
    if len(edges) > 1 and edges[1][0] - nearest[0] < _COLUMN_MARGIN:
        return None
    return nearest[1]


def _norm_token(text) -> str:
    return re.sub(r"\s+", "", str(text or "")).upper()


def read_pdf_table(pdf_path: str) -> dict:
    """{"layout", "lines": [{"page", "date", "tokens", "kind", "value", "text"}], "problem"}. A transaction
    line starts with a date left of the amount columns and prints exactly one amount in an amount
    column (charge / credit / amount); balance and remittance-stub amounts are ignored. Lines that do
    not start with a date (invoice subtotals, carried balances, totals) are never transaction lines.
    Rotated words (margin print) are dropped. "problem" set = the PDF can't be used."""
    import pdfplumber

    def problem(text):
        return {"layout": None, "lines": [], "problem": text}

    lines, geometry, layout, saw_text, printed_amounts = [], None, None, False, set()
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            words = [w for w in page.extract_words() if w.get("upright", True)]
            saw_text = saw_text or bool(words)
            printed_amounts |= {round(abs(v), 2) for v in (_c2_money(w["text"]) for w in words) if v is not None}
            for line in _group_lines(words):
                found = _c2_header(line)
                if found:
                    if layout and found["layout"] != layout:
                        return problem(f"p{page_number}: a second, different column header")
                    geometry, layout = found, found["layout"]
                    continue
                if not _C2_DATE_RE.match(line[0]["text"]):
                    continue
                text = " ".join(w["text"] for w in line)
                if geometry is None:
                    return problem(f"p{page_number}: transaction line before any column header: {text!r}")
                if line[0]["x1"] >= geometry["left"]:
                    continue   # a date printed right of the table (remittance stub, footer): not a transaction
                amounts, tokens = [], []
                for w in line[1:]:
                    value = _c2_money(w["text"])
                    if value is None:
                        if w["x1"] < geometry["text_right"]:
                            tokens.append(_norm_token(w["text"]))
                        continue
                    column = _c2_column(w["x1"], geometry)
                    if column is None:
                        return problem(f"p{page_number}: amount {w['text']} can't be placed in one column: {text!r}")
                    if column in (CHARGE, CREDIT, AMOUNT):
                        amounts.append((column, value))
                if len(amounts) != 1 or not tokens:
                    return problem(f"p{page_number}: line without exactly one amount in an amount column "
                                   f"and a reference: {text!r}")
                kind, value = amounts[0]
                if kind == CREDIT and value < 0:
                    return problem(f"p{page_number}: negative amount under the credit column: {text!r}")
                lines.append({"page": page_number, "date": line[0]["text"], "tokens": tokens, "kind": kind,
                              "value": round(value, 2), "text": text})
    if not saw_text:
        return problem("no text layer (scan)")
    if geometry is None:
        return problem("no CHARGES / CREDITS or AMOUNT column header")
    if not lines:
        return problem("no transaction lines found")
    return {"layout": layout, "lines": lines, "problem": None, "printed_amounts": printed_amounts}


def _c2_raw_keys(invoices: list, layout: str) -> Optional[dict]:
    """The extraction's own raw column names for the layout's amount columns (exactly one each)."""
    keys = set()
    for inv in invoices:
        keys |= set((inv.get("_raw_row") or {}).keys())
    found = {}
    for kind in ((CHARGE, CREDIT) if layout == "charge_credit" else (AMOUNT,)):
        names = [k for k in keys if isinstance(k, str) and re.sub(r"[^A-Z]", "", k.upper()) in _RAW_KEYS[kind]]
        if len(names) != 1:
            return None
        found[kind] = names[0]
    return found


def _c2_row_amount(inv: dict, layout: str) -> tuple:
    """(kind, value) the row carries now: (None, None) when it has no amount; ("both", None) when it has
    a charge and a credit (never corrected)."""
    charge, credit = inv.get("outstanding_amount"), inv.get("credit")
    has_charge, has_credit = charge not in (None, 0), credit not in (None, 0)
    if has_charge and has_credit:
        return "both", None
    if layout == "amount":
        if has_credit:
            return AMOUNT, round(-abs(credit), 2)
        return (AMOUNT, round(charge, 2)) if has_charge else (None, None)
    if has_credit:
        return CREDIT, round(abs(credit), 2)
    return (CHARGE, round(charge, 2)) if has_charge else (None, None)


def _c2_row_tokens(inv: dict, raw_keys: dict) -> list:
    """The row's printed text words (reference, PO#/MEMO, source, description...), used only to tell
    apart printed lines that share a reference and a date."""
    amount_keys = set(raw_keys.values())
    out = []
    for key, value in (inv.get("_raw_row") or {}).items():
        if key in amount_keys or key == "confidence" or not isinstance(value, str) or _C2_DATE_RE.match(value.strip()):
            continue
        out += [_norm_token(t) for t in value.split() if t.strip()]
    return out


def plan_text_row_corrections(invoices: list, pdf_path: Optional[str], printed: Optional[float]) -> dict:
    """{"applicable": bool, "reason": str, "corrections": [...], "pdf_total": float or None}. Reads only."""
    def refuse(reason, **extra):
        return {"applicable": False, "reason": reason, "corrections": [], **extra}

    if not pdf_path or not os.path.exists(pdf_path):
        return refuse("no PDF")
    if printed is None:
        return refuse("no printed total")
    rows = [inv for inv in invoices or [] if not inv.get("informational")]
    if not rows:
        return refuse("no extracted rows")
    try:
        pdf = read_pdf_table(pdf_path)
    except Exception as e:   # an unreadable PDF never changes anything
        return refuse(f"PDF not readable ({type(e).__name__})")
    if pdf["problem"]:
        return refuse(pdf["problem"])
    layout, lines = pdf["layout"], pdf["lines"]
    raw_keys = _c2_raw_keys(rows, layout)
    if raw_keys is None:
        return refuse("the extraction's columns do not match the PDF's " +
                      ("CHARGES / CREDITS columns" if layout == "charge_credit" else "AMOUNT column"))
    pdf_total = round(sum(-l["value"] if l["kind"] == CREDIT else l["value"] for l in lines), 2)
    if abs(pdf_total - printed) > _CENT:
        return refuse(f"the PDF's columns total {pdf_total:,.2f}, not the printed {printed:,.2f}", pdf_total=pdf_total)

    # Identity: reference + date must pick exactly one printed line; where several lines share them
    # (RH Long's payment batch 220830, an NYE invoice and its credit memo on one day), the row's printed
    # words (reference, PO#/MEMO, source...) must be exactly the words the line prints left of its amounts.
    claimed, pairs = {}, []
    for index, inv in enumerate(rows):
        number = inv.get("row_number") or index + 1
        label = f"row {number} ({inv.get('invoice_number')})"
        ref, date = _norm_token(inv.get("invoice_number")), str(inv.get("invoice_date") or "").strip()
        if not ref or not date:
            return refuse(f"{label} has no reference or date", pdf_total=pdf_total)
        candidates = [i for i, l in enumerate(lines) if l["date"] == date and ref in l["tokens"]]
        if len(candidates) > 1:
            words = sorted(_c2_row_tokens(inv, raw_keys))
            candidates = [i for i in candidates if sorted(lines[i]["tokens"]) == words]
        if len(candidates) != 1:
            return refuse(f"{label} {date}: matches {len(candidates)} printed lines, not exactly one", pdf_total=pdf_total)
        if candidates[0] in claimed:
            return refuse(f"{label} and row {claimed[candidates[0]]} claim the same printed line", pdf_total=pdf_total)
        claimed[candidates[0]] = number
        kind, value = _c2_row_amount(inv, layout)
        if kind == "both":
            return refuse(f"{label} has both a charge and a credit", pdf_total=pdf_total)
        pairs.append((inv, kind, value, lines[candidates[0]]))
    left = len(lines) - len(claimed)
    if left:
        return refuse(f"{left} printed line(s) match no extracted row", pdf_total=pdf_total)

    corrections, changes = [], []
    for inv, kind, value, line in pairs:
        if (kind, value) == (line["kind"], line["value"]):
            continue
        if kind is None:
            change = "filled"
        elif kind != line["kind"] and abs(value) == abs(line["value"]):
            change = "moved"
        elif round(abs(value), 2) in pdf["printed_amounts"]:
            change = "replaced"   # the model took another printed number (NYE: a subtotal, the next line's amount)
        else:
            return refuse(f"row {inv.get('row_number')} ({inv.get('invoice_number')}): extracted {value:,.2f} differs "
                          f"from its printed {line['value']:,.2f} and is printed nowhere on the PDF", pdf_total=pdf_total)
        corrections.append({"row_number": inv.get("row_number"), "invoice_number": inv.get("invoice_number"),
                            "date": line["date"], "change": change, "extracted_field": kind,
                            "extracted_value": value, "field": line["kind"], "printed_value": line["value"],
                            "page": line["page"], "printed_line": line["text"]})
        changes.append((inv, line["kind"], line["value"]))
    if not corrections:
        return refuse("the extraction already agrees with the PDF line by line", pdf_total=pdf_total)
    return {"applicable": True, "reason": "", "corrections": corrections, "pdf_total": pdf_total,
            "layout": layout, "raw_keys": raw_keys, "_changes": changes}


def apply_text_row_corrections(plan: dict) -> int:
    """Writes each planned row's printed amount into its printed column, in place (the fields
    apply_text_column_corrections uses, plus the extraction's raw column). Returns the rows changed."""
    raw_keys = plan["raw_keys"]
    for inv, kind, value in plan["_changes"]:
        raw = inv.get("_raw_row")
        if kind == CREDIT:
            for key in ("outstanding_amount", "amount", "charges"):
                inv[key] = None
            inv["credit"] = inv["credits"] = value
            if isinstance(raw, dict):
                raw[raw_keys[CHARGE]], raw[raw_keys[CREDIT]] = None, value
        else:
            for key in ("credit", "credits"):
                inv[key] = None
            inv["outstanding_amount"] = inv["amount"] = inv["charges"] = value
            if isinstance(raw, dict):
                if kind == CHARGE:
                    raw[raw_keys[CREDIT]], raw[raw_keys[CHARGE]] = None, value
                else:
                    raw[raw_keys[AMOUNT]] = value
    return len(plan["_changes"])
