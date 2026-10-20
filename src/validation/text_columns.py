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

TEXT_COLUMN_CORRECTION_ENABLED=false switches the correction off (default on).
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
