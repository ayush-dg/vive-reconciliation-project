"""
payment_column.py

A bare "Payment" column the client left unmapped (2026-10-26, Blue Sun
Quonset STMT-B0E5C001). ClaudeSonnetClient._map_columns() leaves a column
headed exactly "Payment" unmapped on a document with no balance column: on
Blue Sun's earlier statements the printed total is the sum of Amount and the
payments settle a previous balance, and mapping it broke two statements that
passed on Oct 1. The Sep 30 statement prints a previous balance instead:
15,510.89 + 4,479.94 - 6,754.82 = 13,236.01, and its "14-Sep-26 Pymt
6,754.82" row then carried no amount at all.

The correction (tried by the intake only on a statement that still fails,
on a copy first; PAYMENT_COLUMN_CORRECTION_ENABLED=false switches it off)
maps that column as a credit ONLY when every one of these holds:
  - exactly one extracted column is headed exactly "Payment" (the client's
    EXACT_CREDIT_HEADERS), it holds a value on at least one row, and no row
    took a credit from it (the client's rule left it unmapped);
  - no row has an amount due (a balance column would have mapped it already);
  - every row with a payment has no charge of its own;
  - a verified previous balance and a printed total exist, and previous
    balance + the rows' amounts - the payments = printed total to the cent
    (the statement equation).
The caller keeps it only if the whole gate then passes by statement_equation.
Otherwise nothing changes -- the column stays unmapped, exactly as now. A
statement that passes as it is never reaches this, so the Oct 1 statements
the client's rule protects cannot change.
"""

import os
from typing import Optional

ENV_FLAG = "PAYMENT_COLUMN_CORRECTION_ENABLED"
NOT_APPLICABLE = "no unmapped \"Payment\" column"
_CENT = 0.005


def enabled() -> bool:
    return os.getenv(ENV_FLAG, "true").strip().lower() != "false"


def _number(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def plan_payment_column(invoices: list, printed, previous_balance) -> dict:
    """{"applicable", "reason", "column", "payments": [{"row_number", "date", "payment"}], "payments_total",
    "equation"}; changes nothing. invoices: the statement's rows; previous_balance: the gate's verified one."""
    from src.ai.claude_sonnet_client import EXACT_CREDIT_HEADERS
    from src.validation.arithmetic_gate import _row_net
    rows = [inv for inv in invoices or [] if not inv.get("informational")]

    def header(key):
        return str(key).lower().strip().replace("_", " ")
    keys = []
    for inv in rows:
        keys += [k for k in (inv.get("_raw_row") or {}) if header(k) in EXACT_CREDIT_HEADERS and k not in keys]
    paid = [inv for inv in rows if keys and _number((inv.get("_raw_row") or {}).get(keys[0])) not in (None, 0.0)]
    if not keys or not paid:
        return {"applicable": False, "reason": NOT_APPLICABLE}
    if len(keys) > 1:
        return {"applicable": False, "reason": f"{len(keys)} columns headed \"Payment\" ({keys})"}
    column = keys[0]
    if any(inv.get("credit") for inv in paid):
        return {"applicable": False, "reason": NOT_APPLICABLE}
    if any(inv.get("amount_due") is not None for inv in rows):
        return {"applicable": False, "reason": "the statement has an amount-due (balance) column"}
    if any(inv.get("outstanding_amount") for inv in paid):
        return {"applicable": False, "reason": "a row with a payment also has a charge"}
    if printed is None or previous_balance is None:
        return {"applicable": False, "reason": "no printed total or no verified previous balance"}
    payments = [{"row_number": inv.get("row_number"), "date": inv.get("invoice_date"),
                 "payment": round(abs(_number(inv["_raw_row"][column])), 2), "_inv": inv} for inv in paid]
    amounts = round(sum(_row_net(inv) for inv in rows), 2)
    total = round(sum(p["payment"] for p in payments), 2)
    computed = round(previous_balance + amounts - total, 2)
    equation = (f"previous balance {previous_balance:,.2f} + amounts {amounts:,.2f} - payments {total:,.2f} "
                f"= {computed:,.2f}, printed {printed:,.2f}")
    if abs(round(computed - printed, 2)) >= _CENT:
        return {"applicable": False, "reason": f"the equation does not close: {equation}"}
    return {"applicable": True, "reason": "", "column": column, "payments": payments, "payments_total": total,
            "equation": equation}


def apply_payment_column(plan: dict) -> int:
    """Sets each paid row's credit to its payment (in place). Returns the number of rows changed."""
    if not plan.get("applicable"):
        return 0
    for p in plan["payments"]:
        p["_inv"]["credit"] = p["payment"]
        p["_inv"]["credits"] = p["payment"]
    return len(plan["payments"])


def record(plan: dict) -> list:
    return [{k: v for k, v in p.items() if k != "_inv"} | {"column": plan["column"]} for p in plan["payments"]]
