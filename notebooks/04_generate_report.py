"""
04_generate_report.py

Generates a complete reconciliation report for a given statement_id.
Reads all Gold tables and prints a structured summary.

Usage:
    python notebooks/04_generate_report.py --statement-id STMT-TEST-001
    python notebooks/04_generate_report.py --statement-id STMT-TEST-001 --explain

With --explain flag: calls the active AI provider (Azure OpenAI gpt-5-mini) to add AI explanations to open exceptions
before printing the report.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows' default console codepage (cp1252) can't encode every character
# that might appear here (checkmarks, AI-generated text) — force UTF-8
# regardless of the console's active codepage.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from src.lakehouse.connection import execute_query
from src.ai.explanation_service import ExplanationService


def generate_report(statement_id: str, run_explanations: bool = False,
                    max_explanations: int = 10):
    print(f"\n{'='*65}")
    print(f"  VENDOR STATEMENT RECONCILIATION REPORT")
    print(f"{'='*65}")

    # 1. Get summary
    summary_rows = execute_query(
        """
        SELECT * FROM gold_reconciliation_summary
        WHERE statement_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        [statement_id]
    )

    if not summary_rows:
        print(f"\nNo reconciliation summary found for statement_id: {statement_id}")
        print("Run notebooks/03_run_matching.py first.")
        return

    s = summary_rows[0]

    # Get intake log for additional metadata
    intake_rows = execute_query(
        "SELECT * FROM document_intake_log WHERE statement_id = ? LIMIT 1",
        [statement_id]
    )
    intake = intake_rows[0] if intake_rows else {}

    print(f"\n  STATEMENT SUMMARY")
    print(f"  {'-'*60}")
    print(f"  Statement ID:       {statement_id}")
    print(f"  Vendor:             {intake.get('vendor_name') or s.get('vendor_id') or 'unknown'}")
    print(f"  Source file:        {intake.get('source_file', 'unknown')}")
    print(f"  Statement period:   {s.get('statement_period', 'unknown')}")
    print(f"  Extraction method:  {intake.get('extraction_method', 'unknown')}")
    print(f"  Extraction conf.:   {intake.get('extraction_confidence_overall', 'N/A')}")
    print(f"  Reconciled at:      {s.get('reconciliation_timestamp', 'unknown')}")
    print(f"  ERP version:        {s.get('erp_version', 'unknown')}")

    print(f"\n  RECONCILIATION RESULTS")
    print(f"  {'-'*60}")

    status_icon = "✓" if s['overall_status'] == 'RECONCILED' else "!"
    print(f"  [{status_icon}] Status:              {s['overall_status']}")
    print(f"  Total invoices:     {s['total_invoice_count']}")
    print(f"  Matched:            {s['matched_count']} ({s['match_percentage']}%)")
    print(f"  Exceptions:         {s['exception_count']}")
    print(f"  Statement total:    ${s['statement_total']:>12,.2f}")
    print(f"  ERP total:          ${s['erp_total']:>12,.2f}")
    print(f"  Difference:         ${s['difference']:>12,.2f}")

    # 2. Exceptions section
    exceptions = execute_query(
        """
        SELECT * FROM gold_exceptions
        WHERE statement_id = ?
        ORDER BY exception_reason, invoice_number
        """,
        [statement_id]
    )

    if exceptions:
        # Run AI explanations if requested
        if run_explanations:
            print(f"\n  GENERATING AI EXPLANATIONS...")
            print(f"  {'-'*60}")
            svc = ExplanationService(max_per_run=max_explanations)
            result = svc.explain_all_open_exceptions(statement_id)
            print(f"  Explained: {result['explained']} | "
                  f"Skipped (limit): {result['skipped']} | "
                  f"Failed: {result['failed']}")

            # Re-read with explanations
            exceptions = execute_query(
                """
                SELECT * FROM gold_exceptions
                WHERE statement_id = ?
                ORDER BY exception_reason, invoice_number
                """,
                [statement_id]
            )

        print(f"\n  EXCEPTIONS ({len(exceptions)} total)")
        print(f"  {'-'*60}")

        for exc in exceptions:
            print(f"\n  [{exc['exception_reason']}]")
            print(f"  Invoice:      {exc['invoice_number']}")
            print(f"  RO Number:    {exc.get('ro_number') or 'N/A'}")
            print(f"  Stmt Amount:  ${exc.get('statement_amount', 0):,.2f}")
            if exc.get('erp_amount'):
                print(f"  ERP Amount:   ${exc.get('erp_amount', 0):,.2f}")
                print(f"  Difference:   ${(exc['statement_amount'] - exc['erp_amount']):,.2f}")
            else:
                print(f"  ERP Amount:   not in ERP")
            print(f"  Status:       {exc.get('exception_status', 'OPEN')}")

            if exc.get('ai_explanation'):
                print(f"\n  AI Analysis (via {exc.get('ai_provider', 'unknown')}, "
                      f"confidence: {exc.get('ai_confidence_score', 'N/A')}):")
                print(f"  Probable cause:      {exc['ai_explanation']}")
                print(f"  Suggested action:    {exc['ai_suggested_resolution']}")
            else:
                if not run_explanations:
                    print(f"  AI Analysis:  (run with --explain to generate)")

    else:
        print(f"\n  EXCEPTIONS")
        print(f"  {'-'*60}")
        print(f"  No exceptions — statement is fully reconciled.")

    # 3. Matched invoices sample
    matched_count = execute_query(
        "SELECT COUNT(*) as cnt FROM gold_matched_invoices WHERE statement_id = ?",
        [statement_id]
    )[0]["cnt"]

    sample_matched = execute_query(
        """
        SELECT invoice_number, statement_amount, erp_amount, match_level
        FROM gold_matched_invoices
        WHERE statement_id = ?
        ORDER BY statement_amount DESC
        LIMIT 5
        """,
        [statement_id]
    )

    print(f"\n  MATCHED INVOICES (top 5 by amount, {matched_count} total)")
    print(f"  {'-'*60}")
    print(f"  {'Invoice':<20} {'Stmt Amount':>12} {'ERP Amount':>12} {'Level':>6}")
    print(f"  {'-'*55}")
    for m in sample_matched:
        print(f"  {m['invoice_number']:<20} "
              f"${m['statement_amount']:>11,.2f} "
              f"${m['erp_amount']:>11,.2f} "
              f"  L{m['match_level']}")

    # 4. AI Audit summary
    audit_rows = execute_query(
        """
        SELECT interaction_type, ai_provider, model, success, latency_ms
        FROM ai_audit_log
        WHERE statement_id = ?
        ORDER BY request_timestamp DESC
        """,
        [statement_id]
    )

    if audit_rows:
        print(f"\n  AI ACTIVITY LOG ({len(audit_rows)} calls)")
        print(f"  {'-'*60}")
        for a in audit_rows:
            status = "OK" if a['success'] else "FAIL"
            latency = f"{a['latency_ms']/1000:.1f}s" if a['latency_ms'] else "N/A"
            print(f"  [{status}] {a['interaction_type']:<28} "
                  f"{a['ai_provider']:<8} {a['model']:<25} {latency}")

    # 5. Next steps
    print(f"\n  NEXT STEPS")
    print(f"  {'-'*60}")
    if s['exception_count'] == 0:
        print(f"  Statement is fully reconciled. No action required.")
        print(f"  Archive statement_id {statement_id} as RECONCILED.")
    else:
        print(f"  1. Review the {s['exception_count']} exceptions above")
        print(f"  2. Contact vendor or internal team to resolve each exception")
        print(f"  3. Once resolved, update config/mock_erp/scenario_config.json")
        print(f"  4. Re-run: python notebooks/02_generate_mock_erp.py --statement-id {statement_id}")
        print(f"  5. Re-run: python notebooks/03_run_matching.py --statement-id {statement_id}")
        print(f"  6. Re-run: python notebooks/04_generate_report.py --statement-id {statement_id}")

    print(f"\n{'='*65}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate reconciliation report")
    parser.add_argument("--statement-id", required=True, help="Statement ID")
    parser.add_argument("--explain", action="store_true",
                        help="Generate AI explanations for open exceptions before reporting")
    parser.add_argument("--max-explanations", type=int, default=10,
                        help="Max exceptions to explain per run (default: 10)")
    args = parser.parse_args()

    generate_report(
        statement_id=args.statement_id,
        run_explanations=args.explain,
        max_explanations=args.max_explanations,
    )
