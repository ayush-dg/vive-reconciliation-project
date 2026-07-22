"""
azure_sql_migrations.py

Creates the full lakehouse schema directly in Azure SQL using T-SQL DDL.
This is the Azure-SQL equivalent of the SQLite migrations under
migrations/ (001_initial_schema.sql, 002_exception_dispositions.sql,
003_add_blob_storage_path.sql) — same end-state schema, T-SQL syntax:

    TEXT       -> NVARCHAR(MAX)   (NVARCHAR(255) where the column is UNIQUE
                                    or indexed — SQL Server can't key/index
                                    a MAX-length column)
    INTEGER    -> INT
    REAL       -> FLOAT
    AUTOINCREMENT -> IDENTITY(1,1)
    PRAGMA statements -> none (not applicable to Azure SQL)

Safe to re-run: every CREATE TABLE / CREATE INDEX is guarded by an
IF NOT EXISTS check against sys.tables / sys.indexes.

See RULES.md RULE-12 (SQLite migration discipline) and RULE-13 (Azure SQL
as the Phase 3 production backend) — this file is a one-shot schema
creator for the Azure SQL side, not a tracked/numbered migration runner
like src/lakehouse/migrations.py; the SQLite migration files remain the
source of truth for schema history.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.lakehouse.connection import get_connection

TABLES = {
    "bronze_vendor_statement_raw": """
        CREATE TABLE bronze_vendor_statement_raw (
            id INT IDENTITY(1,1) PRIMARY KEY,
            vendor_id NVARCHAR(MAX),
            vendor_name NVARCHAR(MAX),
            source_file NVARCHAR(MAX) NOT NULL,
            statement_id NVARCHAR(MAX) NOT NULL,
            statement_period NVARCHAR(MAX),
            page_number INT,
            [row_number] INT,
            ingestion_timestamp NVARCHAR(MAX) NOT NULL,
            raw_invoice_number NVARCHAR(MAX),
            raw_invoice_date NVARCHAR(MAX),
            raw_due_date NVARCHAR(MAX),
            raw_amount NVARCHAR(MAX),
            raw_outstanding_amount NVARCHAR(MAX),
            raw_ro_number NVARCHAR(MAX),
            raw_po_number NVARCHAR(MAX),
            raw_work_order_number NVARCHAR(MAX),
            raw_description NVARCHAR(MAX),
            raw_credit NVARCHAR(MAX),
            raw_shop_name NVARCHAR(MAX),
            raw_currency NVARCHAR(MAX),
            extraction_confidence FLOAT,
            extraction_model NVARCHAR(MAX),
            raw_ai_response NVARCHAR(MAX)
        )
    """,
    "bronze_internal_erp_raw": """
        CREATE TABLE bronze_internal_erp_raw (
            id INT IDENTITY(1,1) PRIMARY KEY,
            vendor_id NVARCHAR(MAX),
            [source] NVARCHAR(MAX) NOT NULL DEFAULT 'MOCK_ERP',
            statement_id NVARCHAR(MAX) NOT NULL,
            statement_period NVARCHAR(MAX),
            ingestion_timestamp NVARCHAR(MAX) NOT NULL,
            raw_invoice_number NVARCHAR(MAX),
            raw_invoice_date NVARCHAR(MAX),
            raw_posting_date NVARCHAR(MAX),
            raw_amount NVARCHAR(MAX),
            raw_outstanding_amount NVARCHAR(MAX),
            raw_ro_number NVARCHAR(MAX),
            raw_po_number NVARCHAR(MAX),
            raw_shop NVARCHAR(MAX),
            raw_status NVARCHAR(MAX) DEFAULT 'POSTED',
            erp_version INT DEFAULT 1
        )
    """,
    "silver_reconciliation_standard": """
        CREATE TABLE silver_reconciliation_standard (
            id INT IDENTITY(1,1) PRIMARY KEY,
            record_id NVARCHAR(255) UNIQUE NOT NULL,
            record_source NVARCHAR(50) NOT NULL CHECK(record_source IN ('VENDOR_STATEMENT', 'INTERNAL_ERP')),
            document_type NVARCHAR(MAX),
            statement_id NVARCHAR(MAX) NOT NULL,
            statement_date NVARCHAR(MAX),
            vendor_id NVARCHAR(MAX),
            vendor_name NVARCHAR(MAX),
            shop NVARCHAR(MAX),
            invoice_number NVARCHAR(MAX),
            invoice_number_normalized NVARCHAR(MAX),
            invoice_date NVARCHAR(MAX),
            ro_number NVARCHAR(MAX),
            po_number NVARCHAR(MAX),
            work_order_number NVARCHAR(MAX),
            amount FLOAT,
            credit FLOAT,
            outstanding_amount FLOAT,
            due_date NVARCHAR(MAX),
            posting_date NVARCHAR(MAX),
            status NVARCHAR(MAX),
            description NVARCHAR(MAX),
            currency NVARCHAR(MAX),
            statement_period NVARCHAR(MAX),
            source_file NVARCHAR(MAX),
            ingestion_timestamp NVARCHAR(MAX)
        )
    """,
    "gold_matched_invoices": """
        CREATE TABLE gold_matched_invoices (
            id INT IDENTITY(1,1) PRIMARY KEY,
            match_id NVARCHAR(255) UNIQUE NOT NULL,
            vendor_id NVARCHAR(MAX),
            shop NVARCHAR(MAX),
            invoice_number NVARCHAR(MAX),
            ro_number NVARCHAR(MAX),
            statement_amount FLOAT,
            erp_amount FLOAT,
            match_level INT,
            match_status NVARCHAR(MAX) DEFAULT 'MATCHED',
            statement_record_id NVARCHAR(MAX),
            erp_record_id NVARCHAR(MAX),
            source_file NVARCHAR(MAX),
            statement_id NVARCHAR(MAX),
            match_timestamp NVARCHAR(MAX),
            statement_period NVARCHAR(MAX)
        )
    """,
    "gold_exceptions": """
        CREATE TABLE gold_exceptions (
            id INT IDENTITY(1,1) PRIMARY KEY,
            exception_id NVARCHAR(255) UNIQUE NOT NULL,
            vendor_id NVARCHAR(MAX),
            shop NVARCHAR(MAX),
            invoice_number NVARCHAR(MAX),
            ro_number NVARCHAR(MAX),
            statement_amount FLOAT,
            erp_amount FLOAT,
            match_status NVARCHAR(MAX) DEFAULT 'EXCEPTION',
            exception_reason NVARCHAR(MAX),
            exception_status NVARCHAR(MAX) DEFAULT 'OPEN',
            statement_record_id NVARCHAR(MAX),
            source_file NVARCHAR(MAX),
            statement_id NVARCHAR(MAX),
            date_raised NVARCHAR(MAX),
            date_resolved NVARCHAR(MAX),
            statement_period NVARCHAR(MAX),
            ai_explanation NVARCHAR(MAX),
            ai_suggested_resolution NVARCHAR(MAX),
            ai_confidence_score FLOAT,
            ai_provider NVARCHAR(MAX)
        )
    """,
    "gold_reconciliation_summary": """
        CREATE TABLE gold_reconciliation_summary (
            id INT IDENTITY(1,1) PRIMARY KEY,
            summary_id NVARCHAR(255) UNIQUE NOT NULL,
            vendor_id NVARCHAR(MAX),
            vendor_name NVARCHAR(MAX),
            shop NVARCHAR(MAX),
            statement_period NVARCHAR(MAX),
            statement_id NVARCHAR(MAX),
            statement_total FLOAT,
            erp_total FLOAT,
            difference FLOAT,
            total_invoice_count INT,
            matched_count INT,
            exception_count INT,
            match_percentage FLOAT,
            overall_status NVARCHAR(MAX),
            reconciliation_timestamp NVARCHAR(MAX),
            erp_version INT
        )
    """,
    "document_intake_log": """
        CREATE TABLE document_intake_log (
            id INT IDENTITY(1,1) PRIMARY KEY,
            document_id NVARCHAR(255) UNIQUE NOT NULL,
            document_hash NVARCHAR(MAX),
            source_file NVARCHAR(MAX) NOT NULL,
            ingestion_timestamp NVARCHAR(MAX) NOT NULL,
            document_type NVARCHAR(MAX),
            document_type_confidence FLOAT,
            vendor_name NVARCHAR(MAX),
            shop_or_entity NVARCHAR(MAX),
            statement_date NVARCHAR(MAX),
            statement_period NVARCHAR(MAX),
            currency NVARCHAR(MAX),
            statement_total_as_printed FLOAT,
            extraction_confidence_overall FLOAT,
            extraction_model NVARCHAR(MAX),
            extraction_method NVARCHAR(MAX),
            routing_decision NVARCHAR(MAX),
            statement_id NVARCHAR(MAX),
            invoice_count INT,
            warnings NVARCHAR(MAX),
            schema_version NVARCHAR(MAX) DEFAULT '1.0',
            blob_storage_path NVARCHAR(MAX),
            original_filename NVARCHAR(MAX),
            uploaded_by NVARCHAR(MAX),
            uploaded_at NVARCHAR(MAX)
        )
    """,
    "ai_audit_log": """
        CREATE TABLE ai_audit_log (
            id INT IDENTITY(1,1) PRIMARY KEY,
            audit_id NVARCHAR(255) UNIQUE NOT NULL,
            source_file NVARCHAR(MAX),
            vendor_id NVARCHAR(MAX),
            statement_id NVARCHAR(MAX),
            interaction_type NVARCHAR(MAX) NOT NULL,
            ai_provider NVARCHAR(MAX),
            model NVARCHAR(MAX),
            prompt_version NVARCHAR(MAX),
            request_timestamp NVARCHAR(MAX) NOT NULL,
            latency_ms FLOAT,
            attempt_count INT DEFAULT 1,
            success INT NOT NULL,
            response_status NVARCHAR(MAX),
            error_message NVARCHAR(MAX),
            extraction_confidence FLOAT,
            validation_result NVARCHAR(MAX)
        )
    """,
    "validation_document_review_queue": """
        CREATE TABLE validation_document_review_queue (
            id INT IDENTITY(1,1) PRIMARY KEY,
            review_id NVARCHAR(255) UNIQUE NOT NULL,
            vendor_id NVARCHAR(MAX),
            source_file NVARCHAR(MAX),
            statement_id NVARCHAR(MAX),
            statement_period NVARCHAR(MAX),
            pipeline_stage NVARCHAR(MAX),
            rejection_category NVARCHAR(MAX),
            rejection_details NVARCHAR(MAX),
            extraction_confidence FLOAT,
            confidence_threshold_applied FLOAT,
            raw_payload NVARCHAR(MAX),
            review_status NVARCHAR(MAX) DEFAULT 'PENDING_REVIEW',
            flagged_timestamp NVARCHAR(MAX) NOT NULL,
            reviewed_by NVARCHAR(MAX),
            reviewed_timestamp NVARCHAR(MAX),
            resolution_notes NVARCHAR(MAX)
        )
    """,
    "extraction_cache": """
        CREATE TABLE extraction_cache (
            id INT IDENTITY(1,1) PRIMARY KEY,
            document_hash NVARCHAR(255) NOT NULL,
            statement_id NVARCHAR(255) NOT NULL,
            source_file NVARCHAR(MAX),
            extraction_method NVARCHAR(MAX),
            row_count INT,
            ingestion_timestamp NVARCHAR(MAX),
            CONSTRAINT uq_extraction_cache_hash_stmt UNIQUE(document_hash, statement_id)
        )
    """,
    "exception_dispositions": """
        CREATE TABLE exception_dispositions (
            id INT IDENTITY(1,1) PRIMARY KEY,
            exception_id NVARCHAR(MAX) NOT NULL,
            statement_id NVARCHAR(MAX) NOT NULL,
            vendor_name NVARCHAR(255) NOT NULL,
            invoice_number NVARCHAR(255) NOT NULL,
            reason_code NVARCHAR(255),
            disposition_status NVARCHAR(50) NOT NULL CHECK(disposition_status IN
                ('ACCEPTED', 'DISPUTED', 'DUPLICATE', 'WRITE_OFF', 'PENDING')),
            disposition_notes NVARCHAR(MAX),
            disposed_by NVARCHAR(MAX),
            disposed_at NVARCHAR(MAX),
            created_at NVARCHAR(MAX) NOT NULL DEFAULT CONVERT(NVARCHAR(MAX), SYSUTCDATETIME(), 120)
        )
    """,
    "users": """
        CREATE TABLE users (
            id INT IDENTITY(1,1) PRIMARY KEY,
            name NVARCHAR(255) NOT NULL,
            email NVARCHAR(255) UNIQUE NOT NULL,
            password_hash NVARCHAR(255) NOT NULL,
            is_active INT NOT NULL DEFAULT 1,
            created_at NVARCHAR(MAX) NOT NULL,
            created_by NVARCHAR(255)
        )
    """,
    "jobs": """
        CREATE TABLE jobs (
            id INT IDENTITY(1,1) PRIMARY KEY,
            job_id NVARCHAR(255) UNIQUE NOT NULL,
            pdf_filename NVARCHAR(MAX) NOT NULL,
            pdf_path NVARCHAR(MAX) NOT NULL,
            statement_id NVARCHAR(MAX),
            status NVARCHAR(50) NOT NULL DEFAULT 'PENDING' CHECK(status IN
                ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')),
            submitted_by NVARCHAR(255),
            submitted_at NVARCHAR(255) NOT NULL,
            started_at NVARCHAR(MAX),
            completed_at NVARCHAR(MAX),
            error_message NVARCHAR(MAX),
            vendor_name NVARCHAR(MAX),
            claim_token NVARCHAR(255)
        )
    """,
}

INDEXES = {
    "idx_exception_dispositions_lookup": (
        "exception_dispositions",
        "CREATE INDEX idx_exception_dispositions_lookup "
        "ON exception_dispositions(vendor_name, invoice_number, reason_code)",
    ),
    "idx_jobs_status_submitted": (
        "jobs",
        "CREATE INDEX idx_jobs_status_submitted ON jobs(status, submitted_at)",
    ),
}

# Columns added to a table that already exists (a real CREATE TABLE above
# only ever runs for a brand-new database — once "jobs" exists, the
# CREATE TABLE IF NOT EXISTS check for it is always a no-op, so a column
# added to that table's definition here is never actually applied to a
# live Azure SQL database by TABLES alone; it needs its own ALTER TABLE
# entry below, run every time regardless of whether the table itself was
# just created. See migrations/006_add_job_claim_token.sql (the SQLite
# side of this same change) — web/queries.py's claim_next_pending_job()
# needs this column to exist to atomically claim a job.
COLUMNS = {
    "jobs": [
        ("claim_token", "ALTER TABLE jobs ADD claim_token NVARCHAR(255)"),
    ],
}


def run_migrations():
    """Creates every table/index/column listed above that doesn't already
    exist in the connected Azure SQL database. Returns (created_tables,
    created_indexes, created_columns) — names actually created during this
    call.

    Columns are applied last and unconditionally checked even for tables
    that already existed before this call (see COLUMNS) — a table's entry
    in TABLES is only ever used for the initial CREATE TABLE, so a column
    added to an existing table's schema has to be picked up here instead,
    or it silently never reaches a database where that table already
    exists."""
    conn = get_connection()
    created_tables = []
    created_indexes = []
    created_columns = []
    try:
        cursor = conn.cursor()
        for table_name, create_sql in TABLES.items():
            cursor.execute(
                "SELECT 1 FROM sys.tables WHERE name = ?", [table_name]
            )
            if cursor.fetchone():
                continue
            cursor.execute(create_sql)
            conn.commit()
            created_tables.append(table_name)

        for index_name, (table_name, create_sql) in INDEXES.items():
            cursor.execute(
                "SELECT 1 FROM sys.indexes WHERE name = ?", [index_name]
            )
            if cursor.fetchone():
                continue
            cursor.execute(create_sql)
            conn.commit()
            created_indexes.append(index_name)

        for table_name, column_specs in COLUMNS.items():
            for column_name, add_column_sql in column_specs:
                cursor.execute(
                    "SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID(?) AND name = ?",
                    [table_name, column_name],
                )
                if cursor.fetchone():
                    continue
                cursor.execute(add_column_sql)
                conn.commit()
                created_columns.append(f"{table_name}.{column_name}")
    finally:
        conn.close()

    return created_tables, created_indexes, created_columns


def list_tables():
    """Returns the names of all user tables currently in the database."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sys.tables ORDER BY name"
        )
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    if not os.getenv("AZURE_SQL_SERVER"):
        print("AZURE_SQL_SERVER is not set — nothing to do (this script only targets Azure SQL).")
        sys.exit(1)

    created_tables, created_indexes, created_columns = run_migrations()

    if created_tables:
        for name in created_tables:
            print(f"Created table: {name}")
    else:
        print("No new tables — schema already up to date")

    if created_indexes:
        for name in created_indexes:
            print(f"Created index: {name}")

    if created_columns:
        for name in created_columns:
            print(f"Added column: {name}")
    else:
        print("No new columns — schema already up to date")

    print("\nTables now in Azure SQL database:")
    for name in list_tables():
        print(f"  - {name}")
