"""
00_setup_lakehouse_schema.py

Creates every table the reconciliation system needs, using CREATE TABLE IF NOT EXISTS
so re-running is always safe. Run once at project setup.

Locally this targets SQLite via src/lakehouse/connection.py. In production (Microsoft
Fabric), the same DDL structure maps onto Delta tables — only connection.py changes.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse.connection import get_connection

TABLES = {
    "bronze_vendor_statement_raw": """
        CREATE TABLE IF NOT EXISTS bronze_vendor_statement_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id TEXT,
            vendor_name TEXT,
            source_file TEXT NOT NULL,
            statement_id TEXT NOT NULL,
            statement_period TEXT,
            page_number INTEGER,
            row_number INTEGER,
            ingestion_timestamp TEXT NOT NULL,
            raw_invoice_number TEXT,
            raw_invoice_date TEXT,
            raw_due_date TEXT,
            raw_amount TEXT,
            raw_outstanding_amount TEXT,
            raw_ro_number TEXT,
            raw_po_number TEXT,
            raw_work_order_number TEXT,
            raw_description TEXT,
            raw_credit TEXT,
            raw_shop_name TEXT,
            raw_currency TEXT,
            extraction_confidence REAL,
            extraction_model TEXT,
            raw_ai_response TEXT
        );
    """,
    "bronze_internal_erp_raw": """
        CREATE TABLE IF NOT EXISTS bronze_internal_erp_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id TEXT,
            source TEXT NOT NULL DEFAULT 'MOCK_ERP',
            statement_id TEXT NOT NULL,
            statement_period TEXT,
            ingestion_timestamp TEXT NOT NULL,
            raw_invoice_number TEXT,
            raw_invoice_date TEXT,
            raw_posting_date TEXT,
            raw_amount TEXT,
            raw_outstanding_amount TEXT,
            raw_ro_number TEXT,
            raw_po_number TEXT,
            raw_shop TEXT,
            raw_status TEXT DEFAULT 'POSTED',
            erp_version INTEGER DEFAULT 1
        );
    """,
    "silver_reconciliation_standard": """
        CREATE TABLE IF NOT EXISTS silver_reconciliation_standard (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id TEXT UNIQUE NOT NULL,
            record_source TEXT NOT NULL CHECK(record_source IN ('VENDOR_STATEMENT', 'INTERNAL_ERP')),
            document_type TEXT,
            statement_id TEXT NOT NULL,
            statement_date TEXT,
            vendor_id TEXT,
            vendor_name TEXT,
            shop TEXT,
            invoice_number TEXT,
            invoice_number_normalized TEXT,
            invoice_date TEXT,
            ro_number TEXT,
            po_number TEXT,
            work_order_number TEXT,
            amount REAL,
            credit REAL,
            outstanding_amount REAL,
            due_date TEXT,
            posting_date TEXT,
            status TEXT,
            description TEXT,
            currency TEXT,
            statement_period TEXT,
            source_file TEXT,
            ingestion_timestamp TEXT
        );
    """,
    "gold_matched_invoices": """
        CREATE TABLE IF NOT EXISTS gold_matched_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT UNIQUE NOT NULL,
            vendor_id TEXT,
            shop TEXT,
            invoice_number TEXT,
            ro_number TEXT,
            statement_amount REAL,
            erp_amount REAL,
            match_level INTEGER,
            match_status TEXT DEFAULT 'MATCHED',
            statement_record_id TEXT,
            erp_record_id TEXT,
            source_file TEXT,
            statement_id TEXT,
            match_timestamp TEXT,
            statement_period TEXT
        );
    """,
    "gold_exceptions": """
        CREATE TABLE IF NOT EXISTS gold_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exception_id TEXT UNIQUE NOT NULL,
            vendor_id TEXT,
            shop TEXT,
            invoice_number TEXT,
            ro_number TEXT,
            statement_amount REAL,
            erp_amount REAL,
            match_status TEXT DEFAULT 'EXCEPTION',
            exception_reason TEXT,
            exception_status TEXT DEFAULT 'OPEN',
            statement_record_id TEXT,
            source_file TEXT,
            statement_id TEXT,
            date_raised TEXT,
            date_resolved TEXT,
            statement_period TEXT,
            ai_explanation TEXT,
            ai_suggested_resolution TEXT,
            ai_confidence_score REAL,
            ai_provider TEXT
        );
    """,
    "gold_reconciliation_summary": """
        CREATE TABLE IF NOT EXISTS gold_reconciliation_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            summary_id TEXT UNIQUE NOT NULL,
            vendor_id TEXT,
            vendor_name TEXT,
            shop TEXT,
            statement_period TEXT,
            statement_id TEXT,
            statement_total REAL,
            erp_total REAL,
            difference REAL,
            total_invoice_count INTEGER,
            matched_count INTEGER,
            exception_count INTEGER,
            match_percentage REAL,
            overall_status TEXT,
            reconciliation_timestamp TEXT,
            erp_version INTEGER
        );
    """,
    "document_intake_log": """
        CREATE TABLE IF NOT EXISTS document_intake_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT UNIQUE NOT NULL,
            document_hash TEXT,
            source_file TEXT NOT NULL,
            ingestion_timestamp TEXT NOT NULL,
            document_type TEXT,
            document_type_confidence REAL,
            vendor_name TEXT,
            shop_or_entity TEXT,
            statement_date TEXT,
            statement_period TEXT,
            currency TEXT,
            statement_total_as_printed REAL,
            extraction_confidence_overall REAL,
            extraction_model TEXT,
            extraction_method TEXT,
            routing_decision TEXT,
            statement_id TEXT,
            invoice_count INTEGER,
            warnings TEXT,
            schema_version TEXT DEFAULT '1.0'
        );
    """,
    "ai_audit_log": """
        CREATE TABLE IF NOT EXISTS ai_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_id TEXT UNIQUE NOT NULL,
            source_file TEXT,
            vendor_id TEXT,
            statement_id TEXT,
            interaction_type TEXT NOT NULL,
            ai_provider TEXT,
            model TEXT,
            prompt_version TEXT,
            request_timestamp TEXT NOT NULL,
            latency_ms REAL,
            attempt_count INTEGER DEFAULT 1,
            success INTEGER NOT NULL,
            response_status TEXT,
            error_message TEXT,
            extraction_confidence REAL,
            validation_result TEXT
        );
    """,
    "validation_document_review_queue": """
        CREATE TABLE IF NOT EXISTS validation_document_review_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id TEXT UNIQUE NOT NULL,
            vendor_id TEXT,
            source_file TEXT,
            statement_id TEXT,
            statement_period TEXT,
            pipeline_stage TEXT,
            rejection_category TEXT,
            rejection_details TEXT,
            extraction_confidence REAL,
            confidence_threshold_applied REAL,
            raw_payload TEXT,
            review_status TEXT DEFAULT 'PENDING_REVIEW',
            flagged_timestamp TEXT NOT NULL,
            reviewed_by TEXT,
            reviewed_timestamp TEXT,
            resolution_notes TEXT
        );
    """,
    "extraction_cache": """
        CREATE TABLE IF NOT EXISTS extraction_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_hash TEXT NOT NULL,
            statement_id TEXT NOT NULL,
            source_file TEXT,
            extraction_method TEXT,
            row_count INTEGER,
            ingestion_timestamp TEXT,
            UNIQUE(document_hash, statement_id)
        );
    """,
}


def setup_schema():
    conn = get_connection()
    try:
        for table_name, ddl in TABLES.items():
            conn.execute(ddl)
            print(f"Created (or verified) table: {table_name}")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    setup_schema()

    # Verification
    conn = get_connection()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    conn.close()

    print("\nTables in reconciliation.db:")
    for t in tables:
        print(f"  - {t['name']}")

    print("\nPhase 1 complete — all tables created successfully")
