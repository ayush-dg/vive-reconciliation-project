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
from src.shop_owners import get_shop_owner


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


# ---------------------------------------------------------------------------
# Match confidence scoring (gold_matched_invoices.match_confidence /
# gold_exceptions.match_confidence -- see migrations/008_add_match_confidence.sql)
# ---------------------------------------------------------------------------
#
# Two distinct scales, both stored under the same column name:
#   MATCH_CONFIDENCE           -- how reliable a MATCHED row is (a match on
#                                 exact invoice number + exact amount is far
#                                 more trustworthy than an RO-number match on
#                                 a fuzzy amount).
#   EXCEPTION_MATCH_CONFIDENCE -- how confident the system is that an
#                                 EXCEPTION row is a genuine exception
#                                 rather than a matching error -- an
#                                 entirely different question, scored on
#                                 its own scale.
#
# MATCH_CONFIDENCE covers "PO" and "FUZZY" match types and an
# ("INVOICE", "MISMATCH") tier even though classify_match() can't produce
# any of them today (there is no PO-based matching, and the fuzzy-prefix
# level was deliberately removed -- see the NOTE below; an invoice-number
# match with a mismatched amount always becomes an "Amount Mismatch"
# EXCEPTION, never a MATCHED row). Included anyway so this table doesn't
# need to change again the moment one of those levels is added.
MATCH_CONFIDENCE = {
    ("INVOICE", "EXACT"): 1.00,
    ("INVOICE", "TOLERANCE"): 0.95,
    ("INVOICE", "MISMATCH"): 0.70,
    ("PO", "EXACT"): 0.85,
    ("PO", "TOLERANCE"): 0.80,
    ("RO", "EXACT"): 0.80,
    ("RO", "TOLERANCE"): 0.75,
    ("FUZZY", "EXACT"): 0.60,
    ("FUZZY", "TOLERANCE"): 0.60,
    ("FUZZY", "MISMATCH"): 0.60,
}

# classify_match()'s match_level -> the match-type key MATCH_CONFIDENCE
# uses. Anything else (there is no level 3+ today) falls back to "FUZZY".
MATCH_LEVEL_TO_TYPE = {1: "INVOICE", 2: "RO"}

EXCEPTION_MATCH_CONFIDENCE = {
    "Invoice Missing": 0.90,       # no match found at all -- high confidence it's genuinely missing
    "Amount Mismatch": 0.85,
    "EXTRACTION_INCOMPLETE": 0.50,  # uncertain by definition
}

# Floating-point safety margin for treating two amounts as "exactly equal"
# (as opposed to merely within the matching engine's configured
# tolerance) -- not a business tolerance, just guards against binary
# float representation noise (e.g. 0.1 + 0.2 != 0.3).
EXACT_AMOUNT_EPSILON = 0.005


def _amount_status(stmt_amount, erp_amount) -> str:
    """"EXACT" if the two amounts are equal to the cent, else "TOLERANCE".
    Only meaningful once amounts_match() has already confirmed the two
    amounts fall within the matching engine's configured tolerance --
    this never needs to express "doesn't match at all" for a MATCHED row."""
    if stmt_amount is None or erp_amount is None:
        return "TOLERANCE"
    return "EXACT" if abs(stmt_amount - erp_amount) <= EXACT_AMOUNT_EPSILON else "TOLERANCE"


def score_match_confidence(match_level: int, stmt_amount, erp_amount) -> float:
    """match_confidence for a row about to be written to
    gold_matched_invoices -- see MATCH_CONFIDENCE above."""
    match_type = MATCH_LEVEL_TO_TYPE.get(match_level, "FUZZY")
    return MATCH_CONFIDENCE[(match_type, _amount_status(stmt_amount, erp_amount))]


def score_overall_status(exception_count: int) -> str:
    """gold_reconciliation_summary.overall_status for a given OPEN exception
    count. Extracted so run_matching() and web/queries.py's
    _recompute_summary_counts() (which keeps this table's cached
    exception_count/overall_status from going stale after an exception is
    resolved — see resolve_exception()) apply the identical tiering."""
    if exception_count == 0:
        return "RECONCILED"
    if exception_count <= 3:
        return "MINOR_EXCEPTIONS"
    return "EXCEPTIONS_PRESENT"


def score_exception_confidence(exception_reason: str) -> float:
    """match_confidence for a row about to be written to gold_exceptions --
    see EXCEPTION_MATCH_CONFIDENCE above. Falls back to the
    EXTRACTION_INCOMPLETE score (the most conservative of the three) for
    any exception_reason not in that table, e.g. DUPLICATE_RECORD, which
    Step 7 didn't specify a score for."""
    return EXCEPTION_MATCH_CONFIDENCE.get(exception_reason, 0.50)


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

    # Real voucher-sourced ERP data (scripts/load_voucher_data.py) lives
    # under a synthetic, vendor-scoped statement_id ("VOUCHER-<vendor_id>")
    # independent of any single upload -- unlike mock-generated ERP rows,
    # which are scoped to exactly this statement_id and regenerated per
    # run (src/mock_erp/generator.py). This is now the ONLY source
    # matching reads from -- no fallback to the statement-scoped mock
    # rows. That fallback previously made matching silently succeed
    # against src/mock_erp/generator.py's self-mirrored copy of the same
    # statement's own invoices (see that module's docstring) whenever a
    # vendor had no real voucher data, producing a misleadingly high
    # match rate that looked like real reconciliation but wasn't -- see
    # the conversation this removal came out of. Mock ERP generation
    # itself (run_full_pipeline.py's Phase 2) is untouched and still
    # runs/writes on every upload; its output is simply never read here
    # anymore, for any vendor.
    vendor_id = stmt_rows[0].get("vendor_id") if stmt_rows else None
    erp_rows = (
        execute_query(
            """
            SELECT * FROM silver_reconciliation_standard
            WHERE statement_id = ? AND record_source = 'INTERNAL_ERP'
            ORDER BY id
            """,
            [f"VOUCHER-{vendor_id}"]
        )
        if vendor_id else []
    )

    if not stmt_rows:
        raise ValueError(f"No VENDOR_STATEMENT rows in Silver for statement_id='{statement_id}'")
    if not erp_rows:
        raise ValueError(f"No real voucher-sourced INTERNAL_ERP rows for vendor_id='{vendor_id}' "
                         f"(statement_id='{statement_id}'). Matching no longer falls back to "
                         f"mock-generated ERP data -- load real voucher data for this vendor "
                         f"first (see scripts/load_voucher_data.py).")

    print(f"  [Matching] Statement invoices: {len(stmt_rows)}")
    print(f"  [Matching] ERP invoices: {len(erp_rows)}")

    # Clear Gold tables for this statement (idempotent re-run). Exempt
    # EXTRACTION_INCOMPLETE rows — those are raised by intake for rows that
    # were skipped before ever reaching Silver (see
    # notebooks/01_document_intake.py get_skip_reason()/write_skip_exception()),
    # so matching has no Silver data to reclassify them from; deleting them
    # here would erase them permanently since nothing recreates them.
    now = datetime.now(timezone.utc).isoformat()
    execute_sql("DELETE FROM gold_matched_invoices WHERE statement_id = ?", [statement_id])
    execute_sql(
        "DELETE FROM gold_exceptions WHERE statement_id = ? AND exception_reason != 'EXTRACTION_INCOMPLETE'",
        [statement_id]
    )
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
            match_confidence = score_match_confidence(
                result["match_level"], stmt_amount, erp.get("outstanding_amount")
            )
            execute_sql(
                """
                INSERT INTO gold_matched_invoices (
                    match_id, vendor_id, shop, invoice_number, ro_number,
                    statement_amount, erp_amount, match_level, match_status,
                    statement_record_id, erp_record_id, source_file,
                    statement_id, match_timestamp, statement_period, match_confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'MATCHED', ?, ?, ?, ?, ?, ?, ?)
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
                    match_confidence,
                ]
            )
            matched_count += 1

        else:
            exception_id = str(uuid.uuid4())
            match_confidence = score_exception_confidence(result["exception_reason"])
            shop_owner = get_shop_owner(stmt.get("vendor_id"))
            execute_sql(
                """
                INSERT INTO gold_exceptions (
                    exception_id, vendor_id, shop, invoice_number, ro_number,
                    statement_amount, erp_amount, match_status, exception_reason,
                    exception_status, statement_record_id, source_file,
                    statement_id, date_raised, statement_period, match_confidence,
                    shop_owner
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'EXCEPTION', ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?)
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
                    match_confidence,
                    shop_owner,
                ]
            )
            exception_count += 1

    # Compute totals and write reconciliation summary
    match_pct = round((matched_count / len(stmt_rows)) * 100, 2) if stmt_rows else 0.0
    difference = round(total_statement_amount - total_erp_amount, 2)

    overall_status = score_overall_status(exception_count)

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
