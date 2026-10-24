"""Validation gate (added 2026-10-15): only a statement whose Arithmetic
Validation Gate result is "matches" (printed total == sum of the extracted
lines, within arithmetic_gate's 1-cent tolerance) goes on to Silver and
reconciliation.

Every other result stops the pipeline right after intake: "mismatch" (lines
missing or misread), "total_not_found" (nothing to check the lines against),
"no_line_items", and a missing result. Bronze keeps what was extracted. The
pipeline prints VALIDATION_GATE_MARKER and the reason and exits normally:
extraction worked, so web/worker.py marks the job COMPLETED with a "Not
reconciled -- <reason>" note rather than FAILED (failed jobs are for failed
extractions; a statement with no extracted rows at all still fails on the
worker's zero-rows check). The statement shows as Failed on the Validation
page as before.

VALIDATION_GATE_ENABLED=false turns the gate off (every statement reconciles,
the behaviour before this change).
"""
import os

PASS_STATUS = "matches"


def gate_enabled() -> bool:
    return os.getenv("VALIDATION_GATE_ENABLED", "true").strip().lower() != "false"


def _money(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "unknown"


_FLAG_TEXT = {
    "due_opposite_sign": "amount due {amount_due} has the opposite sign of the row's {row_amount}",
    "due_exceeds_row_amount": "amount due {amount_due} is more than the row's {row_amount}",
    "due_without_amount": "amount due {amount_due} on a row with no charge or credit",
    "invoice_does_not_net": "its {rows} rows net to {rows_net}, amount due {amount_due}",
}


def describe_invoice_balance_flag(flag) -> str:
    """One flag of the invoice-balance check in words (also the Validation
    page's filter, web/deps.py)."""
    flag = flag or {}
    values = {k: (_money(v) if k in ("amount_due", "row_amount", "rows_net") else v) for k, v in flag.items()}
    try:
        return _FLAG_TEXT.get(flag.get("rule"), "{rule}").format(**values)
    except (KeyError, IndexError):
        return str(flag.get("rule"))


def describe_invoice_balance_flags(validation, limit: int = 5) -> str:
    """"" when the invoice-balance check (arithmetic_gate.check_invoice_balance,
    2026-10-19) flagged nothing, otherwise the flagged invoices in words."""
    report = ((validation or {}).get("detail") or {}).get("invoice_balance") or {}
    flags = report.get("flags") or []
    if not flags:
        return ""
    parts = [f"{flag.get('invoice_number') or 'row ' + str(flag.get('row_number'))} "
             f"({describe_invoice_balance_flag(flag)})" for flag in flags[:limit]]
    more = (report.get("flag_count") or len(flags)) - len(parts)
    return "; ".join(parts) + (f"; and {more} more" if more > 0 else "")


def describe_failure(validation) -> str:
    """None when the statement may be reconciled, otherwise why not."""
    validation = validation or {}
    status = validation.get("status")
    if status == PASS_STATUS:
        return None
    flagged = describe_invoice_balance_flags(validation)
    if status == "mismatch" and flagged and (validation.get("detail") or {}).get("blocked_pass"):
        # The total matched, but the amount-due column disagrees with the rows.
        return f"Validation failed: invoice balance check -- {flagged}"
    if status == "mismatch":
        detail = f"off by {_money(validation.get('difference'))}"
        if validation.get("printed") is not None and validation.get("computed") is not None:
            detail = (f"printed total {_money(validation['printed'])}, extracted lines sum to "
                      f"{_money(validation['computed'])} ({detail})")
        if flagged:
            detail += f"; invoice balance check: {flagged}"
        return f"Validation failed: {detail}"
    if status == "total_not_found":
        return "Validation failed: no printed statement total was found to check the extracted lines against"
    if status == "no_line_items":
        return "Validation failed: no line items were extracted"
    return f"Validation failed: no validation result ({status!r})"
