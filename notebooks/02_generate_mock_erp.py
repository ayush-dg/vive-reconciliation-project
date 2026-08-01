"""
02_generate_mock_erp.py

Generates the Mock ERP dataset for a given statement_id.
Edit config/mock_erp/scenario_config.json to control which exceptions are planted,
then re-run this script (without re-running the AI extraction) to update the ERP data.

Usage:
    python notebooks/02_generate_mock_erp.py --statement-id STMT-TEST-001

Re-reconciliation workflow:
    1. Edit config/mock_erp/scenario_config.json (add/remove missing invoices, etc.)
    2. python notebooks/02_generate_mock_erp.py --statement-id STMT-TEST-001
    3. python notebooks/03_run_matching.py --statement-id STMT-TEST-001
    4. See updated reconciliation results
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Windows' default console codepage (cp1252) can't encode characters like
# the arrows used below and crashes with UnicodeEncodeError instead of
# printing them — force UTF-8 regardless of the console's active codepage.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Explicit absolute path, matching web/app.py — see
# notebooks/01_document_intake.py for why a bare load_dotenv() is unsafe here.
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from src.mock_erp.generator import generate_mock_erp, normalize_erp_to_silver


def run(statement_id: str):
    print(f"\n{'='*60}")
    print(f"MOCK ERP GENERATOR")
    print(f"Statement ID: {statement_id}")
    print(f"Config: config/mock_erp/scenario_config.json")
    print(f"{'='*60}")

    print(f"\n[Step 1] Generating Mock ERP from Silver VENDOR_STATEMENT rows...")
    counts = generate_mock_erp(statement_id)

    print(f"\n  ERP generation complete:")
    print(f"    Source rows:       {counts['total_source']}")
    print(f"    ERP rows written:  {counts['erp_rows_written']}")
    print(f"    ERP version:       {counts['erp_version']}")
    print(f"    Exact matches:     {counts['exact_match']}")
    print(f"    Missing (skipped): {counts['missing']}")
    print(f"    Amount mismatches: {counts['amount_mismatch']}")
    print(f"    Duplicates added:  {counts['duplicate']}")
    print(f"    Pending posting:   {counts['pending']}")
    print(f"    Renumbered:        {counts['renumbered']}")

    print(f"\n[Step 2] Normalizing ERP Bronze → Silver (INTERNAL_ERP)...")
    silver_count = normalize_erp_to_silver(statement_id)
    print(f"  Silver ERP rows written: {silver_count}")

    print(f"\n{'='*60}")
    print(f"MOCK ERP COMPLETE")
    print(f"  Statement ID:    {statement_id}")
    print(f"  ERP version:     {counts['erp_version']}")
    print(f"  Statement rows:  {counts['total_source']}")
    print(f"  ERP rows:        {counts['erp_rows_written']}")
    print(f"  Exceptions planted:")
    print(f"    Missing:   {counts['missing']}")
    print(f"    Mismatch:  {counts['amount_mismatch']}")
    print(f"    Duplicate: {counts['duplicate']}")
    print(f"    Pending:   {counts['pending']}")
    print(f"    Renumbered: {counts['renumbered']}")
    print(f"{'='*60}")
    print(f"\nNext step: python notebooks/03_run_matching.py --statement-id {statement_id}")

    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Mock ERP dataset for reconciliation")
    parser.add_argument("--statement-id", required=True, help="Statement ID from document intake")
    args = parser.parse_args()
    run(args.statement_id)
