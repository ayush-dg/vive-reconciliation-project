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


def describe_failure(validation) -> str:
    """None when the statement may be reconciled, otherwise why not."""
    validation = validation or {}
    status = validation.get("status")
    if status == PASS_STATUS:
        return None
    if status == "mismatch":
        detail = f"off by {_money(validation.get('difference'))}"
        if validation.get("printed") is not None and validation.get("computed") is not None:
            detail = (f"printed total {_money(validation['printed'])}, extracted lines sum to "
                      f"{_money(validation['computed'])} ({detail})")
        return f"Validation failed: {detail}"
    if status == "total_not_found":
        return "Validation failed: no printed statement total was found to check the extracted lines against"
    if status == "no_line_items":
        return "Validation failed: no line items were extracted"
    return f"Validation failed: no validation result ({status!r})"
