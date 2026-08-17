"""
netsuite_erp.py

Populates Bronze/Silver INTERNAL_ERP rows for a statement from real NetSuite
data (demo_netsuite_bills — see migrations/010_add_demo_netsuite_bills.sql,
scripts/load_netsuite_export.py) instead of the mock ERP generator.

Unlike src/mock_erp/generator.py, which derives ERP rows FROM the vendor
statement's own Silver rows (seeding + controlled exceptions), this reads
the full real NetSuite ledger — independent ground truth — and copies all
of it into Bronze/Silver for this statement_id, exactly as a real
statement-vs-ERP reconciliation would compare against the whole ERP, not
just rows related to one statement.

demo_netsuite_bills has no RO number column (the NetSuite export it was
loaded from doesn't carry one — see scripts/load_netsuite_export.py). Every
row written here has raw_ro_number=None, explicitly, never guessed at.
Pass 2 (RO number + amount) in src/matching/engine.py therefore has no RO
data to match against for any of these rows and falls through to Pass 1's
"Invoice Missing" exception for anything Pass 1 didn't already catch — no
change to engine.py needed for this to happen correctly.

Called from scripts/run_full_pipeline.py's Phase 2, only when the intake
result's vendor_id == "ASTECH" — every other vendor keeps using the mock
ERP generator unchanged.
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lakehouse.connection import execute_sql, execute_query, get_connection
from src.mock_erp.generator import get_next_erp_version, normalize_erp_to_silver

SOURCE_LABEL = "NETSUITE_EXPORT"


def populate_erp_from_netsuite(statement_id: str) -> dict:
    """
    Reads Silver VENDOR_STATEMENT rows for statement_id (for vendor_id /
    statement_period metadata only — the ERP rows themselves come entirely
    from demo_netsuite_bills, not from the statement). Writes the full
    demo_netsuite_bills table into bronze_internal_erp_raw for this
    statement_id, then normalizes to Silver. Idempotent per statement_id
    (deletes and rewrites), same convention as generate_mock_erp().

    Returns a summary dict shaped like generate_mock_erp()'s, so callers
    (scripts/run_full_pipeline.py) can print the same shape of counts
    regardless of which ERP source ran.
    """
    stmt_rows = execute_query(
        """
        SELECT * FROM silver_reconciliation_standard
        WHERE statement_id = ? AND record_source = 'VENDOR_STATEMENT'
        ORDER BY id
        """,
        [statement_id],
    )
    if not stmt_rows:
        raise ValueError(
            f"No Silver VENDOR_STATEMENT rows found for statement_id='{statement_id}'. "
            f"Run 01_document_intake.py first."
        )

    netsuite_rows = execute_query(
        "SELECT invoice_number, amount, bill_date, source_file FROM demo_netsuite_bills ORDER BY id"
    )
    if not netsuite_rows:
        raise ValueError(
            "demo_netsuite_bills is empty — run scripts/load_netsuite_export.py first."
        )

    erp_version = get_next_erp_version(statement_id)
    now = datetime.now(timezone.utc).isoformat()
    vendor_id = stmt_rows[0].get("vendor_id")
    statement_period = stmt_rows[0].get("statement_period")

    execute_sql("DELETE FROM bronze_internal_erp_raw WHERE statement_id = ?", [statement_id])
    execute_sql(
        "DELETE FROM silver_reconciliation_standard WHERE statement_id = ? AND record_source = 'INTERNAL_ERP'",
        [statement_id],
    )

    params = [
        (
            vendor_id,
            SOURCE_LABEL,
            statement_id,
            statement_period,
            now,
            row["invoice_number"],
            row["bill_date"],
            None,  # raw_posting_date -- not available from this NetSuite export
            str(row["amount"]),
            str(row["amount"]),
            None,  # raw_ro_number -- known limitation, see module docstring; never guessed
            None,  # raw_po_number -- not present in this NetSuite export
            None,  # raw_shop -- not present in this NetSuite export
            "POSTED",
            erp_version,
        )
        for row in netsuite_rows
    ]
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if hasattr(cursor, "fast_executemany"):
            cursor.fast_executemany = True
        cursor.executemany(
            """
            INSERT INTO bronze_internal_erp_raw (
                vendor_id, source, statement_id, statement_period,
                ingestion_timestamp, raw_invoice_number, raw_invoice_date,
                raw_posting_date, raw_amount, raw_outstanding_amount,
                raw_ro_number, raw_po_number, raw_shop, raw_status, erp_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params,
        )
        conn.commit()
    finally:
        conn.close()

    silver_count = normalize_erp_to_silver(statement_id, source_file_label=SOURCE_LABEL)

    return {
        "total_source": len(netsuite_rows),
        "erp_rows_written": len(netsuite_rows),
        "silver_erp_rows": silver_count,
        "erp_version": erp_version,
        "source": SOURCE_LABEL,
    }
