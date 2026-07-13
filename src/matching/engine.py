"""
engine.py

Deterministic 2-level matching engine.
Compares Silver VENDOR_STATEMENT rows against Silver INTERNAL_ERP rows.

Match hierarchy (from config/matching/matching_rules.json):
  Level 1: Exact invoice number match (amount must also match within
           tolerance — an invoice-number match with a mismatched amount is
           an Amount Mismatch exception, not a lower match level)
  Level 2: RO number + amount match (within tolerance)

If no level matches → EXCEPTION

AI never touches this. Financial decisions are deterministic and reproducible.

See RULES.md RULE-03.
"""

import json
import os
import sys
import uuid
import hashlib
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.lakehouse.connection import execute_sql, execute_query


def load_matching_rules(config_path: str = "config/matching/matching_rules.json") -> dict:
    with open(config_path, "r") as f:
        return json.load(f)


def amounts_match(stmt_amount: float, erp_amount: float,
                  tolerance_pct: float, tolerance_abs: float) -> bool:
    """Returns True if amounts are within tolerance."""
    if stmt_amount is None or erp_amount is None:
        return False
    diff = abs(stmt_amount - erp_amount)
    pct_diff = diff / max(abs(stmt_amount), 1e-9)
    return diff <= tolerance_abs or pct_diff <= tolerance_pct


def classify_match(stmt_invoice: dict, erp_candidates: list, tolerance_pct: float, tolerance_abs: float) -> dict:
    """
    Try to match one statement invoice against a list of ERP candidates.

    Returns a dict with:
        match_status: 'MATCHED' | 'EXCEPTION'
        match_level: 1 or 2 (None if EXCEPTION)
        matched_erp: the matched ERP row (None if EXCEPTION)
        exception_reason: reason string (None if MATCHED)
        exception_erp_amount: the conflicting ERP amount, only set for
            'Amount Mismatch' exceptions — kept separate from matched_erp
            (which stays None on EXCEPTION) purely for reporting purposes.
    """
    stmt_inv = stmt_invoice.get("invoice_number_normalized") or stmt_invoice.get("invoice_number")
    stmt_ro = stmt_invoice.get("ro_number")
    stmt_amount = stmt_invoice.get("outstanding_amount")

    # Build lookup dicts from ERP candidates
    erp_by_invoice = {}
    erp_by_ro = {}
    for erp in erp_candidates:
        erp_inv = erp.get("invoice_number_normalized") or erp.get("invoice_number")
        erp_ro = erp.get("ro_number")
        if erp_inv:
            erp_by_invoice.setdefault(erp_inv, []).append(erp)
        if erp_ro:
            erp_by_ro.setdefault(erp_ro, []).append(erp)

    # Level 1: Exact invoice number match
    if stmt_inv and stmt_inv in erp_by_invoice:
        candidates = erp_by_invoice[stmt_inv]
        # Among invoice-matched candidates, prefer one where amount also matches
        for erp in candidates:
            if amounts_match(stmt_amount, erp.get("outstanding_amount"), tolerance_pct, tolerance_abs):
                return {
                    "match_status": "MATCHED",
                    "match_level": 1,
                    "matched_erp": erp,
                    "exception_reason": None,
                    "exception_erp_amount": None,
                }
        # Invoice matches but amount doesn't
        return {
            "match_status": "EXCEPTION",
            "match_level": None,
            "matched_erp": None,
            "exception_reason": "Amount Mismatch",
            "exception_erp_amount": candidates[0].get("outstanding_amount"),
        }

    # NOTE: there is deliberately no "fuzzy prefix" level here. An earlier
    # version matched on a truncated invoice-number prefix (e.g. first 6
    # chars) plus amount, intended to catch revision suffixes that survived
    # normalization. In practice, vendor invoice numbers commonly share a
    # long common prefix (e.g. "SIN122...") and flat per-line-item fees
    # repeat constantly, so that heuristic cross-matched unrelated invoices
    # whenever their prefix AND amount coincidentally lined up — silently
    # hiding genuinely missing invoices behind an unrelated match. Level 1
    # (exact invoice_number, via invoice_number_normalized) already covers
    # genuine suffix normalization once a vendor-specific profile is
    # configured; Level 2 (RO + amount) is the correct fallback otherwise.
    # See RULES.md RULE-11.

    # Level 2: RO number + amount
    if stmt_ro and stmt_ro in erp_by_ro:
        for erp in erp_by_ro[stmt_ro]:
            if amounts_match(stmt_amount, erp.get("outstanding_amount"), tolerance_pct, tolerance_abs):
                return {
                    "match_status": "MATCHED",
                    "match_level": 2,
                    "matched_erp": erp,
                    "exception_reason": None,
                    "exception_erp_amount": None,
                }

    # No match found
    return {
        "match_status": "EXCEPTION",
        "match_level": None,
        "matched_erp": None,
        "exception_reason": "Invoice Missing",
        "exception_erp_amount": None,
    }


def run_matching(statement_id: str,
                 rules_path: str = "config/matching/matching_rules.json") -> dict:
    """
    Full matching run for a given statement_id.
    Reads Silver rows for both sides, runs classify_match() per statement invoice,
    writes results to Gold tables.
    Returns a summary dict.
    """
    rules = load_matching_rules(rules_path)
    tolerance_pct = rules.get("amount_tolerance_pct", 0.01)
    tolerance_abs = rules.get("amount_tolerance_abs", 0.50)

    # Read both sides from Silver
    stmt_rows = execute_query(
        """
        SELECT * FROM silver_reconciliation_standard
        WHERE statement_id = ? AND record_source = 'VENDOR_STATEMENT'
        ORDER BY id
        """,
        [statement_id]
    )

    erp_rows = execute_query(
        """
        SELECT * FROM silver_reconciliation_standard
        WHERE statement_id = ? AND record_source = 'INTERNAL_ERP'
        ORDER BY id
        """,
        [statement_id]
    )

    if not stmt_rows:
        raise ValueError(f"No VENDOR_STATEMENT rows in Silver for statement_id='{statement_id}'")
    if not erp_rows:
        raise ValueError(f"No INTERNAL_ERP rows in Silver for statement_id='{statement_id}'. "
                         f"Run 02_generate_mock_erp.py first.")

    print(f"  [Matching] Statement invoices: {len(stmt_rows)}")
    print(f"  [Matching] ERP invoices: {len(erp_rows)}")

    # Clear Gold tables for this statement (idempotent re-run)
    now = datetime.now(timezone.utc).isoformat()
    execute_sql("DELETE FROM gold_matched_invoices WHERE statement_id = ?", [statement_id])
    execute_sql("DELETE FROM gold_exceptions WHERE statement_id = ?", [statement_id])
    execute_sql("DELETE FROM gold_reconciliation_summary WHERE statement_id = ?", [statement_id])

    matched_erp_ids = set()  # track which ERP rows have been consumed
    matched_count = 0
    exception_count = 0
    total_statement_amount = 0.0
    total_erp_amount = 0.0

    for stmt in stmt_rows:
        stmt_amount = stmt.get("outstanding_amount") or 0.0
        total_statement_amount += stmt_amount

        # Filter ERP candidates: not already matched
        available_erp = [
            e for e in erp_rows
            if e["record_id"] not in matched_erp_ids
        ]

        result = classify_match(stmt, available_erp, tolerance_pct, tolerance_abs)

        if result["match_status"] == "MATCHED":
            erp = result["matched_erp"]
            matched_erp_ids.add(erp["record_id"])
            total_erp_amount += erp.get("outstanding_amount") or 0.0

            match_id = str(uuid.uuid4())
            execute_sql(
                """
                INSERT INTO gold_matched_invoices (
                    match_id, vendor_id, shop, invoice_number, ro_number,
                    statement_amount, erp_amount, match_level, match_status,
                    statement_record_id, erp_record_id, source_file,
                    statement_id, match_timestamp, statement_period
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'MATCHED', ?, ?, ?, ?, ?, ?)
                """,
                [
                    match_id,
                    stmt.get("vendor_id"),
                    stmt.get("shop"),
                    stmt.get("invoice_number"),
                    stmt.get("ro_number"),
                    stmt_amount,
                    erp.get("outstanding_amount"),
                    result["match_level"],
                    stmt["record_id"],
                    erp["record_id"],
                    stmt.get("source_file"),
                    statement_id,
                    now,
                    stmt.get("statement_period"),
                ]
            )
            matched_count += 1

        else:
            exception_id = str(uuid.uuid4())
            execute_sql(
                """
                INSERT INTO gold_exceptions (
                    exception_id, vendor_id, shop, invoice_number, ro_number,
                    statement_amount, erp_amount, match_status, exception_reason,
                    exception_status, statement_record_id, source_file,
                    statement_id, date_raised, statement_period
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'EXCEPTION', ?, 'OPEN', ?, ?, ?, ?, ?)
                """,
                [
                    exception_id,
                    stmt.get("vendor_id"),
                    stmt.get("shop"),
                    stmt.get("invoice_number"),
                    stmt.get("ro_number"),
                    stmt_amount,
                    result.get("exception_erp_amount"),  # None unless Amount Mismatch
                    result["exception_reason"],
                    stmt["record_id"],
                    stmt.get("source_file"),
                    statement_id,
                    now,
                    stmt.get("statement_period"),
                ]
            )
            exception_count += 1

    # Compute totals and write reconciliation summary
    match_pct = round((matched_count / len(stmt_rows)) * 100, 2) if stmt_rows else 0.0
    difference = round(total_statement_amount - total_erp_amount, 2)

    if exception_count == 0:
        overall_status = "RECONCILED"
    elif exception_count <= 3:
        overall_status = "MINOR_EXCEPTIONS"
    else:
        overall_status = "EXCEPTIONS_PRESENT"

    # Get ERP version
    erp_version_rows = execute_query(
        "SELECT MAX(erp_version) as v FROM bronze_internal_erp_raw WHERE statement_id = ?",
        [statement_id]
    )
    erp_version = erp_version_rows[0]["v"] if erp_version_rows else 1

    # Get vendor info from Silver
    vendor_row = stmt_rows[0] if stmt_rows else {}

    summary_id = str(uuid.uuid4())
    execute_sql(
        """
        INSERT INTO gold_reconciliation_summary (
            summary_id, vendor_id, vendor_name, shop, statement_period,
            statement_id, statement_total, erp_total, difference,
            total_invoice_count, matched_count, exception_count,
            match_percentage, overall_status, reconciliation_timestamp, erp_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            summary_id,
            vendor_row.get("vendor_id"),
            vendor_row.get("vendor_name"),
            vendor_row.get("shop"),
            vendor_row.get("statement_period"),
            statement_id,
            round(total_statement_amount, 2),
            round(total_erp_amount, 2),
            difference,
            len(stmt_rows),
            matched_count,
            exception_count,
            match_pct,
            overall_status,
            now,
            erp_version,
        ]
    )

    return {
        "statement_id": statement_id,
        "vendor_id": vendor_row.get("vendor_id"),
        "total_invoices": len(stmt_rows),
        "matched_count": matched_count,
        "exception_count": exception_count,
        "match_percentage": match_pct,
        "overall_status": overall_status,
        "statement_total": round(total_statement_amount, 2),
        "erp_total": round(total_erp_amount, 2),
        "difference": difference,
        "erp_version": erp_version,
    }
