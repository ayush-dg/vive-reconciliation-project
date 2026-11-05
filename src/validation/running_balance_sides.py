"""
running_balance_sides.py

Amounts read on the wrong side of a running balance (2026-11-05, Elite Auto
Glass STMT-ADEF9707: Date / Transaction / Reference / Invoiced / Paid /
Balance). The statement's Balance column is a RUNNING balance: each row's
balance = the previous one + its charge - its payment. The AI put the 21
payments of Oct 30 under Invoiced instead of Paid, so they counted as
charges -- yet the printed balance on each of those rows went DOWN by exactly
that amount, which says on which side it belongs.

The correction (tried by the intake only on a statement that still fails, on
a copy first; RUNNING_BALANCE_SIDES_ENABLED=false switches it off):
  - needs at least MIN_ROWS rows with a balance (amount_due);
  - walks the rows in order, starting from the verified previous balance
    (else from the first row's balance, whose own row can't be checked);
  - a row holding only a charge whose balance moved DOWN by exactly that
    amount (to the cent) becomes a payment; a row holding only a payment
    whose balance moved UP by exactly that amount becomes a charge. A row
    with both, or with neither, is never moved;
  - is kept only if afterwards the running balance holds on EVERY row with a
    balance, and the caller then keeps it only if the whole validation gate
    passes. Otherwise nothing changes.
A per-row open-balance column (Keystone-style) never chains, so it is never
touched; a statement that passes as it is never reaches this.
"""

import os
from typing import Optional

ENV_FLAG = "RUNNING_BALANCE_SIDES_ENABLED"
MIN_ROWS = 5
_CENT = 0.005
NOT_APPLICABLE = "no running balance column"

_CHARGE_KEYS = ("outstanding_amount", "amount", "charges")
_CREDIT_KEYS = ("credit", "credits")


def enabled() -> bool:
    return os.getenv(ENV_FLAG, "true").strip().lower() != "false"


def _number(value) -> Optional[float]:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _charge(inv: dict) -> Optional[float]:
    return next((_number(inv.get(k)) for k in _CHARGE_KEYS if _number(inv.get(k)) is not None), None)


def _credit(inv: dict) -> Optional[float]:
    value = next((_number(inv.get(k)) for k in _CREDIT_KEYS if _number(inv.get(k)) is not None), None)
    return None if value is None else abs(value)


def _delta(charge, credit) -> float:
    return (charge or 0.0) - (credit or 0.0)


def plan_running_balance_sides(invoices: list, previous_balance=None) -> dict:
    """{"applicable", "reason", "moves": [{"index", "to", "amount", ...}], "rows"}.
    Changes nothing."""
    plan = {"applicable": False, "reason": NOT_APPLICABLE, "moves": [], "rows": 0}
    with_balance = [inv for inv in invoices or [] if _number(inv.get("amount_due")) is not None]
    plan["rows"] = len(with_balance)
    if len(with_balance) < MIN_ROWS:
        if with_balance:
            plan["reason"] = f"only {len(with_balance)} row(s) with a balance (needs {MIN_ROWS})"
        return plan

    previous = _number(previous_balance)
    moves, breaks = [], 0
    for index, inv in enumerate(invoices):
        charge, credit = _charge(inv), _credit(inv)
        balance = _number(inv.get("amount_due"))
        if balance is None:
            if previous is not None:
                previous += _delta(charge, credit)
            continue
        if previous is not None and abs(previous + _delta(charge, credit) - balance) >= _CENT:
            moved = balance - previous
            if charge and not credit and abs(moved + charge) < _CENT:
                moves.append({"index": index, "to": "credit", "amount": round(charge, 2)})
            elif credit and not charge and abs(moved - credit) < _CENT:
                moves.append({"index": index, "to": "charge", "amount": round(credit, 2)})
            else:
                breaks += 1
        previous = balance

    if breaks:
        plan["reason"] = (f"the running balance does not hold on {breaks} row(s) even with amounts moved "
                          f"to the other side")
        return plan
    if not moves:
        plan["reason"] = "the running balance already holds on every row; nothing on the wrong side"
        return plan
    plan.update(applicable=True, moves=moves,
                reason=f"{len(moves)} amount(s) on the wrong side of the running balance")
    return plan


def apply_running_balance_sides(plan: dict, invoices: list) -> int:
    """Moves each planned amount to its side IN PLACE. Returns how many moved."""
    for move in plan.get("moves") or []:
        inv = invoices[move["index"]]
        if move["to"] == "credit":
            for key in _CHARGE_KEYS:
                inv[key] = None
            for key in _CREDIT_KEYS:
                inv[key] = move["amount"]
        else:
            for key in _CREDIT_KEYS:
                inv[key] = None
            for key in _CHARGE_KEYS:
                inv[key] = move["amount"]
    return len(plan.get("moves") or [])


def record(plan: dict, invoices: list) -> list:
    """What moved, for validation detail["running_balance_corrections"]."""
    out = []
    for move in plan.get("moves") or []:
        inv = invoices[move["index"]]
        out.append({"row_number": move["index"] + 1, "invoice_number": inv.get("invoice_number"),
                    "date": inv.get("invoice_date"), "amount": move["amount"],
                    "from": "charge" if move["to"] == "credit" else "payment", "to": "payment" if move["to"] == "credit" else "charge",
                    "balance": _number(inv.get("amount_due"))})
    return out
