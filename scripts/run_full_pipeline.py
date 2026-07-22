"""
run_full_pipeline.py

Runs the complete reconciliation pipeline for a PDF in one command.

Usage:
    python scripts/run_full_pipeline.py --pdf sample_data/ASTCollex0526.pdf
    python scripts/run_full_pipeline.py --pdf sample_data/ASTCollex0526.pdf --explain
    python scripts/run_full_pipeline.py --pdf sample_data/ASTCollex0526.pdf --statement-id STMT-CUSTOM-001

What it runs:
    1. Document Intake (AI extraction → Bronze → Silver)
    2. Mock ERP Generation (Silver → Mock ERP Bronze → Silver ERP)
    3. Matching Engine (Silver both sides → Gold tables)
    4. Report (with optional AI exception explanations)
"""

import argparse
import importlib.util
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Windows' default console codepage (cp1252) can't encode every character
# that might appear here — force UTF-8 regardless of the console's active codepage.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Explicit absolute path, matching web/app.py — a bare load_dotenv() finds
# .env via cwd/call-stack heuristics, which is one more thing that can go
# wrong depending on how this script gets invoked (e.g. as a subprocess
# from web/worker.py) and silently leave AZURE_SQL_SERVER unset, sending
# this process to the local SQLite db instead of the Azure SQL the web app
# uses — see src/lakehouse/connection.py's _using_azure_sql().
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


def load_notebook(name, relative_path):
    """
    Load a notebooks/*.py script as an importable module.
    Avoids import-path gymnastics for scripts that were never meant to be
    package members — they're numbered CLI entry points, not a package.
    """
    path = os.path.join(PROJECT_ROOT, relative_path)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    parser = argparse.ArgumentParser(description="Run the full reconciliation pipeline")
    parser.add_argument("--pdf", required=True, help="Path to vendor statement PDF")
    parser.add_argument("--statement-id", help="Optional statement ID (auto-generated if not set)")
    parser.add_argument("--period", help="Statement period override, e.g. 2026-05")
    parser.add_argument("--explain", action="store_true",
                        help="Generate AI explanations for exceptions")
    parser.add_argument("--max-explanations", type=int, default=5,
                        help="Max exceptions to explain (default: 5)")
    args = parser.parse_args()

    print(f"\n{'#'*65}")
    print(f"  FULL RECONCILIATION PIPELINE")
    print(f"  PDF: {args.pdf}")
    print(f"{'#'*65}")

    # Phase 1: Document Intake
    print(f"\n>>> PHASE 1: Document Intake")
    intake_mod = load_notebook("intake", "notebooks/01_document_intake.py")
    intake_result = intake_mod.run_intake(
        pdf_path=args.pdf,
        statement_id=args.statement_id,
        statement_period=args.period,
    )
    statement_id = intake_result["statement_id"]
    print(f"    Statement ID: {statement_id}")

    if intake_result.get("bronze_count", 0) == 0:
        print(f"\n{'#'*65}")
        print(f"  PIPELINE STOPPED — no invoices extracted")
        print(f"  Statement ID: {statement_id}")
        print(f"  All extraction paths (AI providers, OCR, pdfplumber) ran but")
        print(f"  produced zero usable invoice rows — see Phase 1 output above")
        print(f"  for which providers failed and why (e.g. quota exhaustion).")
        print(f"  Nothing to generate a Mock ERP or match against.")
        print(f"{'#'*65}\n")
        return

    # Phase 2: Mock ERP Generation
    print(f"\n>>> PHASE 2: Mock ERP Generation")
    from src.mock_erp.generator import generate_mock_erp, normalize_erp_to_silver
    counts = generate_mock_erp(statement_id)
    erp_silver = normalize_erp_to_silver(statement_id)
    print(f"    ERP rows: {counts['erp_rows_written']} (version {counts['erp_version']})")
    print(f"    Silver ERP: {erp_silver} rows")
    print(f"    Exceptions planted: {counts['missing']} missing, "
          f"{counts['amount_mismatch']} mismatches, "
          f"{counts['duplicate']} duplicates")

    # Phase 3: Matching
    print(f"\n>>> PHASE 3: Matching Engine")
    from src.matching.engine import run_matching
    summary = run_matching(statement_id)
    print(f"    Matched: {summary['matched_count']}/{summary['total_invoices']} "
          f"({summary['match_percentage']}%)")
    print(f"    Exceptions: {summary['exception_count']}")
    print(f"    Status: {summary['overall_status']}")

    # Phase 4: Report
    print(f"\n>>> PHASE 4: Report")
    report_mod = load_notebook("report", "notebooks/04_generate_report.py")
    report_mod.generate_report(
        statement_id=statement_id,
        run_explanations=args.explain,
        max_explanations=args.max_explanations,
    )

    print(f"\n{'#'*65}")
    print(f"  PIPELINE COMPLETE")
    print(f"  Statement ID: {statement_id}")
    print(f"  Status: {summary['overall_status']}")
    print(f"{'#'*65}\n")


if __name__ == "__main__":
    main()
