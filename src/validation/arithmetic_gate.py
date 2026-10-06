"""
arithmetic_gate.py

Shared Arithmetic Validation Gate -- compares a statement's printed total
against a centrally-computed sum of its extracted line items. Path-agnostic:
both the pdfplumber vendor scripts (via adapter.py's understand()) and the
Foundry/Claude Sonnet vision path (via claude_sonnet_client.py's
_build_schema()) populate statement_total_as_printed/statement_total_computed
in the same statement_metadata shape, so this one function covers both.
"""

import json
import math
import os
import re
from typing import Optional

TOTAL_COLUMNS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "validation_total_columns.json",
)

_total_columns_cache = None


def compute_arithmetic_validation(
    statement_total_as_printed: Optional[float],
    statement_total_computed: Optional[float],
    tolerance: float = 0.01,
) -> dict:
    """Three-state comparison of a statement's printed total vs. the sum of
    its extracted line items.

    Returns {"status": "matches"|"mismatch"|"total_not_found"|"no_line_items",
             "printed": <value>, "computed": <value>, "difference": <value or None>}.

    "no_line_items" (2026-10-06): a statement with a printed total but no
    extracted rows at all (computed is None) used to be reported as a
    mismatch against a computed total of 0 -- Wilbert's Inc.
    STMT-3C442D16 showed as "computed $0, off by $1,373" when the real
    problem was an extraction that produced nothing.
    """
    if statement_total_as_printed is None:
        return {
            "status": "total_not_found",
            "printed": statement_total_as_printed,
            "computed": statement_total_computed,
            "difference": None,
        }

    if statement_total_computed is None:
        return {
            "status": "no_line_items",
            "printed": statement_total_as_printed,
            "computed": None,
            "difference": None,
        }

    difference = round(statement_total_as_printed - statement_total_computed, 2)
    if abs(difference) <= tolerance:
        return {
            "status": "matches",
            "printed": statement_total_as_printed,
            "computed": statement_total_computed,
            "difference": difference,
        }

    return {
        "status": "mismatch",
        "printed": statement_total_as_printed,
        "computed": statement_total_computed,
        "difference": difference,
    }


def compute_statement_total_from_invoices(invoices: list) -> Optional[float]:
    """Centrally-computed sum of a statement's line items, netting credits
    against charges. Both extraction paths (pdfplumber via adapter.py,
    Foundry via claude_sonnet_client.py) normalize every invoice into the
    same two universal-schema keys regardless of vendor-specific field
    names: outstanding_amount (=charges) and credit.

    Two verified real-world shapes for a credit row:
    - Quirk-pattern (Quirk, Fred Beans, Nimey, Lia, Fenix, and tested
      Foundry/Nucar statements): outstanding_amount is None/absent on a
      credit row -- the credit is the row's only real value.
    - ABC-pattern (extract_abc): outstanding_amount carries the SAME face
      value as credit on a credit-memo row (adapter.py's own comment:
      "a Credit Memo row's original_amount is its face value, and its
      actual credit shows up separately in the credit_field") -- naively
      subtracting outstanding_amount - credit cancels the row to 0 and
      loses the credit's real effect.

    Handling both: whenever a row has a real credit value, that credit IS
    the row's contribution (negative) -- outstanding_amount on that same
    row is ignored, since in every verified shape it's either None or a
    duplicate of the credit itself, never a genuinely different charge
    that also needs to be added. Only rows with no credit contribute their
    outstanding_amount.

    A third row shape exists for Keystone specifically: a settlement row
    can have BOTH a real charge (balance_forward) and a real payment
    (payment_applied) that must be netted TOGETHER on that same row --
    unlike ABC-pattern (duplicate value, correctly handled by using only
    credit) or Quirk-pattern (outstanding_amount is None on credit rows).
    Confirmed via investigation: this is the ONLY vendor where both
    balance_forward and payment_applied are genuinely populated on the
    same row, so checking for both being non-null/non-zero is a safe,
    vendor-agnostic signal -- every other vendor's invoices never
    populate these two specific keys at all.

    Two more fixes confirmed via AR Statement_217590_2026_AUG_Tekion.pdf
    (invoice 56763-1R):
    - Sign inversion: some vendors' credit field is stored as a negative
      number rather than a positive magnitude. Naively doing
      `total -= credit` on an already-negative credit ADDS it back
      instead of subtracting it, inverting the row's effect. A credit
      always represents a reduction regardless of the source data's
      sign, so the magnitude is netted via abs(credit).
    - Duplicate reversal rows: the same invoice_number occasionally
      appears more than once for what is really one reversal event --
      once as an outstanding-only row (outstanding_amount set, credit
      None/0) and separately as a credit-only row (credit set,
      outstanding_amount None/0) -- of equal magnitude (56763-1R:
      outstanding_amount=-41.18 on one row, credit=-41.18 on another;
      that same invoice_number can ALSO carry an unrelated genuine
      credit row, e.g. -568.69, which is left untouched since its
      magnitude has no matching outstanding-only row). These are the
      same event recorded twice with a net effect of zero, not two
      distinct transactions -- counting either row (let alone both)
      contributes a spurious non-zero amount for a reversal that never
      actually changed the balance. Before summing, both rows of such a
      matched pair (an outstanding-only row and a credit-only row of the
      exact same magnitude, for the same invoice_number) are dropped
      entirely -- an invoice_number that appears only once, or whose
      rows don't match in magnitude, is left untouched."""
    if not invoices:
        return None

    by_invoice_number = {}
    for inv in invoices:
        num = inv.get("invoice_number")
        if num is not None:
            by_invoice_number.setdefault(num, []).append(inv)

    dropped_ids = set()
    for num, rows in by_invoice_number.items():
        if len(rows) < 2:
            continue
        outstanding_only_rows = [
            row for row in rows
            if row.get("outstanding_amount") and not row.get("credit")
        ]
        credit_only_rows = [
            row for row in rows
            if row.get("credit") and not row.get("outstanding_amount")
        ]
        for outstanding_only in outstanding_only_rows:
            for credit_only in credit_only_rows:
                if id(credit_only) in dropped_ids:
                    continue
                if abs(outstanding_only["outstanding_amount"]) == abs(credit_only["credit"]):
                    # Same reversal recorded on two rows -- its net effect
                    # is zero, so both rows are dropped (not just the
                    # outstanding one): keeping either row would still
                    # double-count/over-net a transaction that never had
                    # any real net effect on the statement.
                    dropped_ids.add(id(outstanding_only))
                    dropped_ids.add(id(credit_only))
                    break

    total = 0.0
    for inv in invoices:
        if id(inv) in dropped_ids:
            continue
        balance_forward = inv.get("balance_forward")
        payment_applied = inv.get("payment_applied")
        if balance_forward and payment_applied:
            # Dual-value settlement row (Keystone) -- net together on this row.
            total += _settlement_net(balance_forward, payment_applied)
            continue
        credit = abs(inv.get("credit") or 0)
        if credit:
            total -= credit
        else:
            total += inv.get("outstanding_amount") or 0
    return round(total, 2)


def _settlement_net(balance_forward: float, payment_applied: float) -> float:
    """A Keystone settlement row's net effect: the payment moves the balance
    forward toward zero, whatever sign either value was printed with.

    Both conventions exist (2026-10-06 replay of every Oct 1 statement):
    the pdfplumber Keystone extractor writes a credit settlement as
    balance_forward=-X, payment_applied=-X (256 rows -- plain bf - pa is
    right there), while Claude returned Keystone (First Choice) row
    G4795354 as balance_forward=16.83, payment_applied=-16.83 (where
    bf - pa gave +33.66). Subtracting abs(pa) fixed the second but turned
    the first into -2X, so the payment's magnitude takes balance_forward's
    sign instead: 0 for (+,+), (-,-), (+,-) and (-,+) alike."""
    return balance_forward - math.copysign(abs(payment_applied), balance_forward)


def _load_total_columns() -> dict:
    global _total_columns_cache
    if _total_columns_cache is None:
        try:
            with open(TOTAL_COLUMNS_PATH, "r") as f:
                raw = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            raw = {}
        _total_columns_cache = {
            vendor_id: entry["column"]
            for vendor_id, entry in raw.items()
            if isinstance(entry, dict) and entry.get("column")
        }
    return _total_columns_cache


def _parse_amount(value) -> Optional[float]:
    """1234.5 / '1,234.50' / '$1,234.50' / '-5.00' / '5.00-' / '($5.00)' -> float; blank -> None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    negative = (s.startswith("(") and s.endswith(")")) or s.endswith("-")
    s = re.sub(r"[()$,\s]", "", s).rstrip("-")
    try:
        number = float(s)
    except ValueError:
        return None
    return -abs(number) if negative else number


def compute_vendor_column_total(vendor_id: Optional[str], invoices: list) -> Optional[float]:
    """Per-vendor override for the gate's computed total (config/
    validation_total_columns.json): the sum of ONE raw extracted column --
    the column the statement's printed total actually adds up -- read from
    each line's _raw_row. Returns None when vendor_id has no override (the
    caller keeps compute_statement_total_from_invoices()'s generic total).

    Exists because the generic total nets outstanding_amount/credit from the
    extraction engine's own column mapping, which is wrong for some layouts:
    NCS's Amount column includes customer-payment rows, A New Age's report
    has no column Claude's mapping recognises as an amount (so it summed $0),
    and Fenix's charged-minus-paid counts credits already absorbed. In each
    case one column sums to the printed total exactly (confirmed 2026-10-01
    on every August statement for these vendors).

    The column key is matched case- and whitespace-insensitively, and None
    is returned when NO row carries that column at all (2026-10-06): the
    configured key ("due" for Fenix) is extract_fenix's snake_case field,
    but a scanned Fenix PDF goes through Claude, whose _raw_row keys are the
    printed headers ("Due"). The exact-key lookup found nothing on any row
    and still returned 0.0, which then replaced a correct generic total
    (Fenix STMT-917D9B0A: generic 2,065.00 = printed, override 0.00)."""
    column = _load_total_columns().get(vendor_id) if vendor_id else None
    if not column or not invoices:
        return None
    wanted = _normalize_column_key(column)
    total = 0.0
    found = 0
    for inv in invoices:
        raw_row = inv.get("_raw_row") or {}
        if not isinstance(raw_row, dict):
            continue
        key = next((k for k in raw_row if _normalize_column_key(k) == wanted), None)
        if key is None:
            continue
        found += 1
        amount = _parse_amount(raw_row.get(key))
        if amount is not None:
            total += amount
    if not found:
        return None
    return round(total, 2)


def _normalize_column_key(key) -> str:
    return re.sub(r"[\s_]+", "", str(key)).lower()


# ---------------------------------------------------------------------------
# Fallback validation chain (2026-10-06)
# ---------------------------------------------------------------------------
#
# The primary check above compares the printed total with charges minus
# credits. Some statement layouts print a total that is arithmetically
# something else -- the sum of a per-row open-balance column, a previous
# balance plus this period's activity, the last value of a running-balance
# column, or per-section subtotals. validate_with_fallbacks() tries those
# alternative identities ONLY when the primary check fails, and each one
# must reproduce the printed figure exactly (same 0.01 tolerance) from
# extracted values. There is no path that accepts a printed total on
# trust, and each check carries guards that make a wrong extraction fail
# (see scratchpad/oct1_report/oct1_root_cause_analysis.md for the Oct 1
# statements each check was designed against).

VALIDATION_METHOD_PRIMARY = "primary"
VALIDATION_METHOD_OPEN_BALANCE = "open_balance"
VALIDATION_METHOD_STATEMENT_EQUATION = "statement_equation"
VALIDATION_METHOD_RUNNING_BALANCE = "running_balance"
VALIDATION_METHOD_SECTION_SUBTOTAL = "section_subtotal"

_MONEY_EPSILON = 0.005  # float noise only -- never widens the 0.01 match rule


def _is_informational(inv: dict) -> bool:
    """A row kept in Bronze for reference that never moves the balance
    (claude_sonnet_client.py flags "LAST PAYMENT ..." notes this way)."""
    return bool(inv.get("informational"))


def _row_net(inv: dict) -> float:
    """One row's signed effect on the balance, exactly as
    compute_statement_total_from_invoices() counts it (minus the reversal-
    pair dropping, which is a whole-statement adjustment, not a per-row one)."""
    balance_forward = inv.get("balance_forward")
    payment_applied = inv.get("payment_applied")
    if balance_forward and payment_applied:
        return _settlement_net(balance_forward, payment_applied)
    credit = abs(inv.get("credit") or 0)
    if credit:
        return -credit
    return inv.get("outstanding_amount") or 0.0


def _rows_for_checks(invoices: list) -> list:
    return [inv for inv in invoices or [] if not _is_informational(inv)]


def _matches(printed: float, computed: float, tolerance: float) -> bool:
    return abs(round(printed - computed, 2)) <= tolerance


def _is_running_balance(rows: list) -> bool:
    """True when amount_due behaves like a cumulative balance: on at least
    80% of consecutive row pairs (minimum 2 pairs) the next row's balance is
    the previous balance plus that row's own amount."""
    comparisons = hits = 0
    previous = None
    for inv in rows:
        due = inv.get("amount_due")
        if due is None:
            previous = None
            continue
        net = _row_net(inv)
        if previous is not None and net:
            comparisons += 1
            if abs(round(previous + net - due, 2)) <= _MONEY_EPSILON:
                hits += 1
        previous = due
    return comparisons >= 2 and hits >= 0.8 * comparisons


def _invoice_group_key(invoice_number):
    """Groups a credit memo with its invoice ("CM9485340" -> "9485340").
    Settlement labels with no digits ("ROA", "Payment", "Debit") are not
    invoice numbers and never form a group."""
    if invoice_number is None:
        return None
    s = str(invoice_number).strip()
    if not re.search(r"\d", s):
        return None
    return re.sub(r"^CM", "", s, flags=re.IGNORECASE)


def _open_balance_preconditions(rows: list):
    """Returns (applicable, reason) for the open-balance check.

    Coverage is measured over CHARGE rows only (a positive row amount):
    credit and payment rows legitimately leave the open-balance column blank
    on some layouts -- Autoly's Due column is empty on every credit/payment
    row, so Bow COLE 0826 (Due on all 9 invoices, blank on 10 credits/
    payments) fell just under "half of all rows" and was never checked even
    though sum(Due) - Unalloc. equals its printed total exactly. This only
    decides whether the check is attempted; the row and invoice guards in
    _check_open_balance() are unchanged."""
    charge_rows = [inv for inv in rows if (inv.get("outstanding_amount") or 0) > 0]
    with_due = [inv for inv in charge_rows if inv.get("amount_due") is not None]
    if not any(inv.get("amount_due") is not None for inv in rows):
        return False, "no open-balance (amount_due) column was extracted"
    if len(with_due) * 2 < len(charge_rows):
        return False, (f"open-balance column on only {len(with_due)} of {len(charge_rows)} "
                       f"charge rows (needs at least half)")
    if _is_running_balance(rows):
        return False, "the amount_due column is a running balance, not a per-row open balance"
    return True, ""


def _check_open_balance(printed, rows, *, tolerance, **_):
    applicable, reason = _open_balance_preconditions(rows)
    if not applicable:
        return {"applicable": False, "passed": False, "computed": None, "reason": reason}

    open_total = sum(inv.get("amount_due") or 0 for inv in rows)
    unallocated = sum(abs(inv.get("unallocated") or 0) for inv in rows)
    computed = round(open_total - unallocated, 2)

    # Guard 1 -- per row: an open balance can never exceed the row's own
    # amount or have the opposite sign (a misplaced value, e.g. a payment
    # sitting in the Amount Due column, or a credit memo read as a charge).
    row_failures = []
    for inv in rows:
        due = inv.get("amount_due")
        if due in (None, 0, 0.0):
            continue
        net = _row_net(inv)
        if due * net < 0 or abs(due) > abs(net) + _MONEY_EPSILON:
            row_failures.append({
                "row_number": inv.get("row_number"), "invoice_number": inv.get("invoice_number"),
                "row_amount": round(net, 2), "open_balance": round(due, 2),
            })

    # Guard 2 -- per invoice: rows sharing one invoice number (charge, credit
    # memo, payments applied to it) must net to that invoice's open balance.
    groups = {}
    for inv in rows:
        key = _invoice_group_key(inv.get("invoice_number"))
        if key is not None:
            groups.setdefault(key, []).append(inv)
    group_failures = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        net_total = round(sum(_row_net(inv) for inv in members), 2)
        due_total = round(sum(inv.get("amount_due") or 0 for inv in members), 2)
        if abs(net_total - due_total) > _MONEY_EPSILON:
            group_failures.append({"invoice_number": key, "rows_net": net_total, "open_balance": due_total})

    result = {
        "applicable": True, "computed": computed,
        "open_balance_total": round(open_total, 2), "unallocated_total": round(unallocated, 2),
    }
    if row_failures or group_failures:
        result.update(passed=False, reason="open-balance column is inconsistent with the extracted row amounts",
                      row_guard_failures=row_failures[:10], invoice_guard_failures=group_failures[:10])
        return result
    if not _matches(printed, computed, tolerance):
        result.update(passed=False, reason=f"sum of open balances {computed:,.2f} does not equal printed {printed:,.2f}")
        return result
    result.update(passed=True, reason="")
    return result


def _check_statement_equation(printed, rows, *, tolerance, previous_balance=None, **_):
    if previous_balance is None:
        return {"applicable": False, "passed": False, "computed": None,
                "reason": "no verified previous balance was extracted"}
    open_item, _ = _open_balance_preconditions(rows)
    if open_item:
        return {"applicable": False, "passed": False, "computed": None,
                "reason": "open-item statement: its rows are open items, not this period's activity"}
    activity = compute_statement_total_from_invoices(rows) or 0.0
    computed = round(previous_balance + activity, 2)
    result = {"applicable": True, "computed": computed,
              "previous_balance": round(previous_balance, 2), "activity_total": round(activity, 2)}
    if not _matches(printed, computed, tolerance):
        result.update(passed=False, reason=(f"previous balance {previous_balance:,.2f} + activity {activity:,.2f} "
                                            f"= {computed:,.2f}, printed {printed:,.2f}"))
        return result
    result.update(passed=True, reason="")
    return result


def _check_running_balance(printed, rows, *, tolerance, previous_balance=None, **_):
    if not rows:
        return {"applicable": False, "passed": False, "computed": None, "reason": "no rows"}
    missing = [inv for inv in rows if inv.get("amount_due") is None]
    if missing:
        return {"applicable": False, "passed": False, "computed": None,
                "reason": f"{len(missing)} of {len(rows)} rows have no balance value"}
    # The opening balance must be a printed figure (or 0 when none is
    # printed), never inferred from the first row -- inferring it would let
    # a dropped first row pass.
    opening = previous_balance if previous_balance is not None else 0.0
    running = opening
    for position, inv in enumerate(rows, start=1):
        expected = round(running + _row_net(inv), 2)
        printed_balance = round(inv.get("amount_due"), 2)
        if abs(expected - printed_balance) > tolerance:
            return {
                "applicable": True, "passed": False, "computed": None, "opening_balance": round(opening, 2),
                "reason": "running balance chain breaks",
                "first_broken_row": {
                    "position": position, "row_number": inv.get("row_number"),
                    "invoice_number": inv.get("invoice_number"), "row_amount": round(_row_net(inv), 2),
                    "expected_balance": expected, "printed_balance": printed_balance,
                },
            }
        running = printed_balance
    computed = round(running, 2)
    result = {"applicable": True, "computed": computed, "opening_balance": round(opening, 2)}
    if not _matches(printed, computed, tolerance):
        result.update(passed=False, reason=f"chain holds but last balance {computed:,.2f} is not printed {printed:,.2f}")
        return result
    result.update(passed=True, reason="")
    return result


def _check_section_subtotal(printed, rows, *, tolerance, section_totals=None, **_):
    if not section_totals:
        return {"applicable": False, "passed": False, "computed": None, "reason": "no printed section subtotals"}
    sections = {}
    for entry in section_totals:
        name = str((entry or {}).get("section") or "").strip()
        subtotal = (entry or {}).get("subtotal")
        if not name or subtotal is None:
            return {"applicable": True, "passed": False, "computed": None,
                    "reason": "a printed section has no name or no subtotal"}
        sections[name] = entry
    unassigned = [inv for inv in rows if str(inv.get("section") or "").strip() not in sections]
    if unassigned:
        return {"applicable": True, "passed": False, "computed": None,
                "reason": f"{len(unassigned)} row(s) do not belong to any printed section"}
    failures, results = [], []
    for name, entry in sections.items():
        members = [inv for inv in rows if str(inv.get("section") or "").strip() == name]
        total = round(sum(_row_net(inv) for inv in members), 2)
        subtotal = round(float(entry["subtotal"]), 2)
        count = entry.get("invoice_count")
        ok = bool(members) and _matches(subtotal, total, tolerance)
        if ok and count is not None and int(count) != len(members):
            ok = False
        results.append({"section": name, "rows": len(members), "rows_total": total,
                        "printed_subtotal": subtotal, "printed_invoice_count": count, "reconciles": ok})
        if not ok:
            failures.append(name)
    computed = round(sum(r["rows_total"] for r in results), 2)
    result = {"applicable": True, "computed": computed, "sections": results,
              "printed_total_is_sum_of_sections": _matches(printed, computed, tolerance)}
    if failures:
        result.update(passed=False, reason=f"section(s) not reconciling: {', '.join(failures)}")
        return result
    result.update(passed=True, reason="")
    return result


_FALLBACK_CHECKS = (
    (VALIDATION_METHOD_OPEN_BALANCE, _check_open_balance),
    (VALIDATION_METHOD_STATEMENT_EQUATION, _check_statement_equation),
    (VALIDATION_METHOD_RUNNING_BALANCE, _check_running_balance),
    (VALIDATION_METHOD_SECTION_SUBTOTAL, _check_section_subtotal),
)


def validate_with_fallbacks(
    statement_total_as_printed: Optional[float],
    statement_total_computed: Optional[float],
    invoices: list,
    *,
    previous_balance: Optional[float] = None,
    section_totals: Optional[list] = None,
    tolerance: float = 0.01,
) -> dict:
    """Primary check, then -- only if it mismatches -- the four fallback
    identities in order. Returns compute_arithmetic_validation()'s dict plus
    "method" (which check passed, or None) and "detail" (every fallback that
    was tried and why it did or didn't pass).

    A fallback pass is stored as status "matches" with its own method, and
    "computed"/"difference" are that check's own figures; the primary
    check's computed total and difference are kept in detail. For a
    section_subtotal pass, "computed" is the sum of the reconciled sections
    -- which differs from "printed" when the printed figure is a group
    total that also covers sections not in this document (detail records
    printed_total_is_sum_of_sections)."""
    result = compute_arithmetic_validation(statement_total_as_printed, statement_total_computed, tolerance)
    result["method"] = None
    result["detail"] = None
    if result["status"] == "matches":
        result["method"] = VALIDATION_METHOD_PRIMARY
        return result
    if result["status"] != "mismatch":
        return result

    rows = _rows_for_checks(invoices)
    printed = statement_total_as_printed
    attempts = []
    for method, check in _FALLBACK_CHECKS:
        outcome = check(printed, rows, tolerance=tolerance,
                        previous_balance=previous_balance, section_totals=section_totals)
        attempts.append({"method": method, **outcome})
        if outcome.get("passed"):
            computed = outcome["computed"]
            return {
                "status": "matches",
                "printed": printed,
                "computed": computed,
                "difference": round(printed - computed, 2),
                "method": method,
                "detail": {
                    "primary_computed": statement_total_computed,
                    "primary_difference": result["difference"],
                    "attempts": attempts,
                },
            }
    result["detail"] = {"attempts": attempts}
    return result
