"""
arithmetic_gate.py

Shared Arithmetic Validation Gate -- compares a statement's printed total
against a centrally-computed sum of its extracted line items. Path-agnostic:
both the pdfplumber vendor scripts (via adapter.py's understand()) and the
Foundry/Claude Sonnet vision path (via claude_sonnet_client.py's
_build_schema()) populate statement_total_as_printed/statement_total_computed
in the same statement_metadata shape, so this one function covers both.
"""

from typing import Optional


def compute_arithmetic_validation(
    statement_total_as_printed: Optional[float],
    statement_total_computed: Optional[float],
    tolerance: float = 0.01,
) -> dict:
    """Three-state comparison of a statement's printed total vs. the sum of
    its extracted line items.

    Returns {"status": "matches"|"mismatch"|"total_not_found",
             "printed": <value>, "computed": <value>, "difference": <value or None>}.
    """
    if statement_total_as_printed is None:
        return {
            "status": "total_not_found",
            "printed": statement_total_as_printed,
            "computed": statement_total_computed,
            "difference": None,
        }

    difference = round(statement_total_as_printed - (statement_total_computed or 0), 2)
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
            total += (balance_forward or 0) - (payment_applied or 0)
            continue
        credit = abs(inv.get("credit") or 0)
        if credit:
            total -= credit
        else:
            total += inv.get("outstanding_amount") or 0
    return round(total, 2)
