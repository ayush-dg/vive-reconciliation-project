"""
payment_rows.py

A payment printed as a statement ROW but read as a positive charge
(2026-11-11, Colonie Garage STMT-91096ABB). Colonie's "Account Activity"
prints no column headings and one amount column, every figure unsigned:

    10/01/26 Previous Balance              $2,354.38
    10/15/26 Order/Invoice Number 300720097 $1,036.17
    10/26/26 Payment - Thank You           $2,354.38
                                   Balance: $1,036.17

The AI read both rows as amounts (+1,036.17 and +2,354.38 = 3,390.55), so the
statement failed validation against the printed 1,036.17 -- on every read,
Sonnet and Opus alike. The row's own words say which side it is on.

The correction (tried by the intake only on a statement that still fails, on
a copy first; PAYMENT_ROWS_CORRECTION_ENABLED=false switches it off) turns
such a row's amount into a credit ONLY when every one of these holds:
  - the row's text says it is a payment ("Payment", "Pymt", "Pmt", "Paid",
    "Thank you", "Remittance") and does not say it is a fee or charge
    ("Late payment fee", "Finance charge", "Interest", "Payment due");
  - the row holds one positive amount and no credit or balance of its own;
  - the printed total is reached to the cent with those rows as credits:
    rows' total - 2 x payments = printed total, or, with a verified previous
    balance, previous balance + that = printed total (the statement equation).
The caller keeps it only if the whole gate then passes. Otherwise nothing
changes. A statement that passes as it is never reaches this.
"""

import os
import re
from typing import Optional

ENV_FLAG = "PAYMENT_ROWS_CORRECTION_ENABLED"
NOT_APPLICABLE = "no row reads as a payment"
_CENT = 0.005

_CHARGE_KEYS = ("outstanding_amount", "amount", "charges")
_CREDIT_KEYS = ("credit", "credits")
_TEXT_KEYS = ("invoice_number", "description", "transaction_code", "reference", "document_type")

PAYMENT_WORDS = re.compile(r"\b(payments?|pymts?|pmts?|paid|thank\s*you|remittance)\b", re.I)
NOT_PAYMENT_WORDS = re.compile(r"\b(fees?|charges?|interest|finance|late|penalty|due|surcharge)\b", re.I)


def enabled() -> bool:
    return os.getenv(ENV_FLAG, "true").strip().lower() != "false"


def _number(value) -> Optional[float]:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def row_text(inv: dict) -> str:
    """Every word the row carries: its text fields and its raw cells."""
    raw = inv.get("_raw_row")
    if isinstance(raw, dict) and any(isinstance(v, str) and v.strip() for v in raw.values()):
        return " ".join(v.strip() for v in raw.values() if isinstance(v, str) and v.strip())
    return " ".join(str(inv.get(k)).strip() for k in _TEXT_KEYS if isinstance(inv.get(k), str) and inv.get(k).strip())


def reads_as_payment(text: str) -> bool:
    return bool(PAYMENT_WORDS.search(text or "")) and not NOT_PAYMENT_WORDS.search(text or "")


def _charge(inv: dict) -> Optional[float]:
    return next((_number(inv.get(k)) for k in _CHARGE_KEYS if _number(inv.get(k)) is not None), None)


def _has_credit_or_balance(inv: dict) -> bool:
    return any(_number(inv.get(k)) not in (None, 0.0) for k in _CREDIT_KEYS + ("amount_due",))


def plan_payment_rows(invoices: list, computed, printed, previous_balance=None) -> dict:
    """{"applicable", "reason", "rows": [{"index", "amount", "text"}], "equation"}; changes nothing.
    computed: the rows' total as validated now; previous_balance: the gate's verified one (or None)."""
    plan = {"applicable": False, "reason": NOT_APPLICABLE, "rows": [], "equation": None}
    rows = []
    for index, inv in enumerate(invoices or []):
        text = row_text(inv)
        if not reads_as_payment(text):
            continue
        amount = _charge(inv)
        if amount is None or amount <= 0 or _has_credit_or_balance(inv):
            continue
        rows.append({"index": index, "amount": round(amount, 2), "text": text.strip()[:120]})
    if not rows:
        return plan
    computed, printed = _number(computed), _number(printed)
    if computed is None or printed is None:
        plan["reason"] = "no printed total or computed total to check against"
        return plan
    payments = round(sum(r["amount"] for r in rows), 2)
    after = round(computed - 2 * payments, 2)
    previous = _number(previous_balance)
    if abs(after - printed) < _CENT:
        equation = f"rows {computed:,.2f} - 2 x payments {payments:,.2f} = {after:,.2f} = printed {printed:,.2f}"
    elif previous is not None and abs(previous + after - printed) < _CENT:
        equation = (f"previous balance {previous:,.2f} + charges {computed - payments:,.2f} - payments "
                    f"{payments:,.2f} = {previous + after:,.2f} = printed {printed:,.2f}")
    else:
        plan["reason"] = (f"with {len(rows)} payment row(s) ({payments:,.2f}) as credits the rows come to "
                          f"{after:,.2f}" + (f" ({previous + after:,.2f} with the previous balance)" if previous is not None else "")
                          + f", not the printed {printed:,.2f}")
        return plan
    plan.update(applicable=True, rows=rows, equation=equation,
                reason=f"{len(rows)} payment row(s) read as charges")
    return plan


def apply_payment_rows(plan: dict, invoices: list) -> int:
    """Turns each planned row's amount into a credit IN PLACE. Returns how many changed."""
    for row in plan.get("rows") or []:
        inv = invoices[row["index"]]
        for key in _CHARGE_KEYS:
            inv[key] = None
        for key in _CREDIT_KEYS:
            inv[key] = row["amount"]
    return len(plan.get("rows") or [])


def record(plan: dict, invoices: list) -> list:
    """What changed, for validation detail["payment_row_corrections"]."""
    return [{"row_number": row["index"] + 1, "text": row["text"], "amount": row["amount"],
             "date": invoices[row["index"]].get("invoice_date")} for row in plan.get("rows") or []]
