"""
generator.py

Generates a realistic Mock ERP dataset seeded from Silver VENDOR_STATEMENT rows.
Applies controlled, deterministic exceptions from scenario_config.json.

This is NOT random. Every exception is explicitly listed in the config,
which makes the re-reconciliation workflow work: edit the config,
re-run the generator, re-run matching → updated results.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.lakehouse.connection import execute_sql, execute_query


def load_scenario_config(config_path: str = "config/mock_erp/scenario_config.json") -> dict:
    with open(config_path, "r") as f:
        return json.load(f)


def get_next_erp_version(statement_id: str) -> int:
    """Returns the next version number for this statement's ERP data."""
    rows = execute_query(
        "SELECT MAX(erp_version) as max_v FROM bronze_internal_erp_raw WHERE statement_id = ?",
        [statement_id]
    )
    current = rows[0]["max_v"] if rows and rows[0]["max_v"] is not None else 0
    return current + 1


def generate_mock_erp(statement_id: str, config_path: str = "config/mock_erp/scenario_config.json") -> dict:
    """
    Main entry point. Reads Silver VENDOR_STATEMENT rows and generates
    a corresponding ERP dataset with controlled exceptions applied.

    Returns a summary dict.
    """
    config = load_scenario_config(config_path)
    controlled = config.get("controlled_exceptions", {})

    missing_invoices = set(controlled.get("missing_invoices", []))
    amount_mismatches = controlled.get("amount_mismatches", {})  # {invoice_number: new_amount}
    duplicate_invoices = controlled.get("duplicate_invoices", [])
    pending_posting = set(controlled.get("pending_posting", []))

    # Read Silver VENDOR_STATEMENT rows for this statement
    silver_rows = execute_query(
        """
        SELECT * FROM silver_reconciliation_standard
        WHERE statement_id = ? AND record_source = 'VENDOR_STATEMENT'
        ORDER BY id
        """,
        [statement_id]
    )

    if not silver_rows:
        raise ValueError(f"No Silver VENDOR_STATEMENT rows found for statement_id='{statement_id}'. "
                         f"Run 01_document_intake.py first.")

    print(f"  [MockERP] Found {len(silver_rows)} Silver rows to seed from")
    print(f"  [MockERP] Controlled exceptions:")
    print(f"    Missing invoices:    {list(missing_invoices) or 'none'}")
    print(f"    Amount mismatches:   {amount_mismatches or 'none'}")
    print(f"    Duplicate invoices:  {duplicate_invoices or 'none'}")
    print(f"    Pending posting:     {list(pending_posting) or 'none'}")

    # Get next ERP version
    erp_version = get_next_erp_version(statement_id)
    now = datetime.now(timezone.utc).isoformat()

    # Delete old ERP Bronze rows for this statement (replace with new version)
    execute_sql(
        "DELETE FROM bronze_internal_erp_raw WHERE statement_id = ?",
        [statement_id]
    )

    # Also delete old Silver INTERNAL_ERP rows
    execute_sql(
        "DELETE FROM silver_reconciliation_standard WHERE statement_id = ? AND record_source = 'INTERNAL_ERP'",
        [statement_id]
    )

    counts = {
        "total_source": len(silver_rows),
        "erp_rows_written": 0,
        "missing": 0,
        "amount_mismatch": 0,
        "duplicate": 0,
        "pending": 0,
        "exact_match": 0,
        "erp_version": erp_version,
    }

    posting_lag_min = config.get("posting_date_lag_days", {}).get("min", 1)
    posting_lag_max = config.get("posting_date_lag_days", {}).get("max", 5)

    erp_rows_to_write = []

    for row in silver_rows:
        invoice_num = row["invoice_number"]

        # Skip missing invoices entirely
        if invoice_num in missing_invoices:
            counts["missing"] += 1
            continue

        # Determine amount
        outstanding = row["outstanding_amount"]
        if invoice_num in amount_mismatches:
            outstanding = amount_mismatches[invoice_num]
            counts["amount_mismatch"] += 1
        else:
            counts["exact_match"] += 1

        # Determine status
        status = "PENDING" if invoice_num in pending_posting else config.get("default_erp_status", "POSTED")
        if invoice_num in pending_posting:
            counts["pending"] += 1

        # Calculate posting date (invoice_date + small lag)
        invoice_date = row.get("invoice_date")
        posting_date = None
        if invoice_date:
            try:
                lag = random.randint(posting_lag_min, posting_lag_max)
                inv_dt = datetime.fromisoformat(invoice_date)
                posting_date = (inv_dt + timedelta(days=lag)).strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                posting_date = None

        erp_row = {
            "vendor_id": row["vendor_id"],
            "statement_id": statement_id,
            "statement_period": row["statement_period"],
            "ingestion_timestamp": now,
            "raw_invoice_number": invoice_num,
            "raw_invoice_date": row.get("invoice_date"),
            "raw_posting_date": posting_date,
            "raw_amount": str(row["amount"]) if row.get("amount") is not None else str(outstanding),
            "raw_outstanding_amount": str(outstanding),
            "raw_ro_number": row.get("ro_number"),
            "raw_po_number": row.get("po_number"),
            "raw_shop": row.get("shop"),
            "raw_status": status,
            "erp_version": erp_version,
        }
        erp_rows_to_write.append(erp_row)

    # Add duplicates
    duplicate_set = set(duplicate_invoices)
    for row in silver_rows:
        if row["invoice_number"] in duplicate_set:
            # Write the original + a duplicate
            erp_row = {
                "vendor_id": row["vendor_id"],
                "statement_id": statement_id,
                "statement_period": row["statement_period"],
                "ingestion_timestamp": now,
                "raw_invoice_number": row["invoice_number"],
                "raw_invoice_date": row.get("invoice_date"),
                "raw_posting_date": None,
                "raw_amount": str(row["amount"]) if row.get("amount") is not None else str(row.get("outstanding_amount")),
                "raw_outstanding_amount": str(row.get("outstanding_amount")),
                "raw_ro_number": row.get("ro_number"),
                "raw_po_number": row.get("po_number"),
                "raw_shop": row.get("shop"),
                "raw_status": "POSTED",
                "erp_version": erp_version,
            }
            erp_rows_to_write.append(erp_row)
            counts["duplicate"] += 1

    # Write all ERP Bronze rows
    for erp_row in erp_rows_to_write:
        execute_sql(
            """
            INSERT INTO bronze_internal_erp_raw (
                vendor_id, source, statement_id, statement_period,
                ingestion_timestamp, raw_invoice_number, raw_invoice_date,
                raw_posting_date, raw_amount, raw_outstanding_amount,
                raw_ro_number, raw_po_number, raw_shop, raw_status, erp_version
            ) VALUES (?, 'MOCK_ERP', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                erp_row["vendor_id"],
                erp_row["statement_id"],
                erp_row["statement_period"],
                erp_row["ingestion_timestamp"],
                erp_row["raw_invoice_number"],
                erp_row["raw_invoice_date"],
                erp_row["raw_posting_date"],
                erp_row["raw_amount"],
                erp_row["raw_outstanding_amount"],
                erp_row["raw_ro_number"],
                erp_row["raw_po_number"],
                erp_row["raw_shop"],
                erp_row["raw_status"],
                erp_row["erp_version"],
            ]
        )
        counts["erp_rows_written"] += 1

    return counts


def normalize_erp_to_silver(statement_id: str):
    """
    Normalize Bronze INTERNAL_ERP rows to silver_reconciliation_standard.
    Mirrors what 01_document_intake.py does for the statement side.
    """
    import hashlib
    from src.normalization import normalize_invoice_number

    erp_rows = execute_query(
        "SELECT * FROM bronze_internal_erp_raw WHERE statement_id = ?",
        [statement_id]
    )

    if not erp_rows:
        return 0

    execute_sql(
        "DELETE FROM silver_reconciliation_standard WHERE statement_id = ? AND record_source = 'INTERNAL_ERP'",
        [statement_id]
    )

    now = datetime.now(timezone.utc).isoformat()
    count = 0

    for row in erp_rows:
        def safe_float(val):
            try:
                return float(val) if val is not None else None
            except (TypeError, ValueError):
                return None

        outstanding = safe_float(row.get("raw_outstanding_amount"))
        amount = safe_float(row.get("raw_amount")) or outstanding
        invoice_number = row.get("raw_invoice_number")
        invoice_number_normalized = normalize_invoice_number(invoice_number)

        record_id = hashlib.sha256(
            f"INTERNAL_ERP|{statement_id}|{invoice_number}|{outstanding}|{row.get('erp_version', 1)}".encode()
        ).hexdigest()

        execute_sql(
            """
            INSERT OR REPLACE INTO silver_reconciliation_standard (
                record_id, record_source, document_type, statement_id,
                statement_date, vendor_id, vendor_name, shop,
                invoice_number, invoice_number_normalized, invoice_date,
                ro_number, po_number, work_order_number,
                amount, credit, outstanding_amount, due_date,
                posting_date, status, description, currency,
                statement_period, source_file, ingestion_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record_id,
                "INTERNAL_ERP",
                "MOCK_ERP_EXTRACT",
                statement_id,
                row.get("statement_period"),
                row.get("vendor_id"),
                None,  # vendor_name not stored in ERP Bronze
                row.get("raw_shop"),
                invoice_number,
                invoice_number_normalized,
                row.get("raw_invoice_date"),
                row.get("raw_ro_number"),
                row.get("raw_po_number"),
                None,  # work_order_number
                amount,
                None,  # credit
                outstanding,
                None,  # due_date
                row.get("raw_posting_date"),
                row.get("raw_status"),
                None,  # description
                None,  # currency
                row.get("statement_period"),
                "MOCK_ERP",
                now,
            ]
        )
        count += 1

    return count
