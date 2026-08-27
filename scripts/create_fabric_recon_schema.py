"""One-shot schema creator for silver.recon_matched_invoices/
recon_exceptions/recon_summary in the Fabric Warehouse -- the NetSuite
matching flow's results (src/matching/fabric_matching.py), read by the
Exceptions page (web/queries.py's recon_query/recon_sql).

Deliberately a standalone script, not a dbt model: these are
application-written operational rows (one INSERT per matched invoice /
exception, from Python, as jobs complete), not a SQL transformation of
raw data -- the same reasoning notebooks/01_document_intake.py's
write_to_bronze()/write_to_review_queue() apply to their own tables, none
of which are dbt models either.

Fabric Warehouse doesn't enforce PRIMARY KEY/UNIQUE constraints (metadata
only, not physically checked) -- uniqueness is handled by
fabric_matching.py's DELETE-then-INSERT per statement_id instead, same
idempotency pattern as write_to_bronze().

Safe to re-run: every CREATE TABLE is guarded by a check against
sys.tables, same pattern as scripts/create_fabric_sqldb_schema.py.

Usage: venv/Scripts/python.exe scripts/create_fabric_recon_schema.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from src.lakehouse.fabric_sql import get_warehouse_connection

TABLES = {
    "recon_matched_invoices": """
        CREATE TABLE silver.recon_matched_invoices (
            match_id VARCHAR(50),
            vendor_id VARCHAR(100),
            shop VARCHAR(200),
            invoice_number VARCHAR(100),
            ro_number VARCHAR(100),
            statement_amount DECIMAL(18,2),
            erp_amount DECIMAL(18,2),
            match_level INT,
            match_status VARCHAR(50),
            statement_id VARCHAR(100),
            match_timestamp DATETIME2(6)
        )
    """,
    "recon_exceptions": """
        CREATE TABLE silver.recon_exceptions (
            exception_id VARCHAR(50),
            vendor_id VARCHAR(100),
            shop VARCHAR(200),
            invoice_number VARCHAR(100),
            ro_number VARCHAR(100),
            statement_amount DECIMAL(18,2),
            erp_amount DECIMAL(18,2),
            match_status VARCHAR(50),
            exception_reason VARCHAR(100),
            exception_status VARCHAR(50),
            statement_id VARCHAR(100),
            date_raised DATETIME2(6),
            date_resolved DATETIME2(6),
            statement_period VARCHAR(50),
            ai_explanation VARCHAR(4000),
            ai_suggested_resolution VARCHAR(4000),
            ai_confidence_score DECIMAL(5,2),
            ai_provider VARCHAR(100),
            match_confidence DECIMAL(5,2),
            shop_owner VARCHAR(200),
            escalation_status VARCHAR(50),
            escalated_at DATETIME2(6),
            escalated_by VARCHAR(200),
            source_file VARCHAR(500)
        )
    """,
    "recon_summary": """
        CREATE TABLE silver.recon_summary (
            summary_id VARCHAR(50),
            vendor_id VARCHAR(100),
            vendor_name VARCHAR(300),
            shop VARCHAR(200),
            statement_period VARCHAR(50),
            statement_id VARCHAR(100),
            statement_total DECIMAL(18,2),
            erp_total DECIMAL(18,2),
            difference DECIMAL(18,2),
            total_invoice_count INT,
            matched_count INT,
            exception_count INT,
            match_percentage DECIMAL(5,2),
            overall_status VARCHAR(50),
            reconciliation_timestamp DATETIME2(6),
            version_number INT,
            previous_statement_id VARCHAR(100),
            is_latest_version BIT
        )
    """,
}


def main():
    conn = get_warehouse_connection()
    cur = conn.cursor()
    for table_name, ddl in TABLES.items():
        cur.execute(
            "SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id "
            "WHERE s.name = 'silver' AND t.name = ?",
            [table_name],
        )
        if cur.fetchone():
            print(f"silver.{table_name} already exists, skipping")
            continue
        cur.execute(ddl)
        conn.commit()
        print(f"created silver.{table_name}")


if __name__ == "__main__":
    main()
