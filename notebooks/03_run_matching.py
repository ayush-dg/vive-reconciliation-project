"""
03_run_matching.py

Runs the deterministic matching engine for a given statement_id.
Produces Gold tables: gold_matched_invoices, gold_exceptions, gold_reconciliation_summary.

Usage:
    python notebooks/03_run_matching.py --statement-id STMT-TEST-001

This is pure Python — no AI, no randomness. Results are fully reproducible.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows' default console codepage (cp1252) can't encode characters like
# the checkmark used below and crashes with UnicodeEncodeError instead of
# printing them — force UTF-8 regardless of the console's active codepage.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from src.matching.engine import run_matching
from src.lakehouse.connection import execute_query


def print_exceptions(statement_id: str):
    """Print a readable list of exceptions."""
    exceptions = execute_query(
        """
        SELECT invoice_number, ro_number, exception_reason, statement_amount, erp_amount
        FROM gold_exceptions
        WHERE statement_id = ?
        ORDER BY exception_reason, invoice_number
        """,
        [statement_id]
    )
    if not exceptions:
        print("  No exceptions!")
        return

    for e in exceptions:
        erp_amt = f"ERP: {e['erp_amount']}" if e['erp_amount'] else "not in ERP"
        print(f"  [{e['exception_reason']}] {e['invoice_number']} | "
              f"Statement: {e['statement_amount']} | {erp_amt}")


def run(statement_id: str):
    print(f"\n{'='*60}")
    print(f"MATCHING ENGINE")
    print(f"Statement ID: {statement_id}")
    print(f"{'='*60}")

    print(f"\n[Step 1] Running deterministic matching...")
    summary = run_matching(statement_id)

    print(f"\n{'='*60}")
    print(f"RECONCILIATION RESULTS")
    print(f"  Statement ID:      {statement_id}")
    print(f"  Vendor:            {summary.get('vendor_id', 'unknown')}")
    print(f"  Total invoices:    {summary['total_invoices']}")
    print(f"  Matched:           {summary['matched_count']} ({summary['match_percentage']}%)")
    print(f"  Exceptions:        {summary['exception_count']}")
    print(f"  Statement total:   ${summary['statement_total']:,.2f}")
    print(f"  ERP total:         ${summary['erp_total']:,.2f}")
    print(f"  Difference:        ${summary['difference']:,.2f}")
    print(f"  Overall status:    {summary['overall_status']}")
    print(f"  ERP version:       {summary['erp_version']}")
    print(f"{'='*60}")

    if summary['exception_count'] > 0:
        print(f"\nExceptions:")
        print_exceptions(statement_id)
        print(f"\nTo resolve: edit config/mock_erp/scenario_config.json, then re-run:")
        print(f"  python notebooks/02_generate_mock_erp.py --statement-id {statement_id}")
        print(f"  python notebooks/03_run_matching.py --statement-id {statement_id}")
    else:
        print(f"\n✓ FULLY RECONCILED — all invoices matched!")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run deterministic matching engine")
    parser.add_argument("--statement-id", required=True, help="Statement ID from document intake")
    args = parser.parse_args()
    run(args.statement_id)
