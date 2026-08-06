"""One-shot schema creator for the new SQL database in Fabric item
(FABRIC_SQLDB_ENDPOINT/FABRIC_SQLDB_NAME) -- creates extraction_cache,
document_intake_log, and validation_document_review_queue with real
IDENTITY(1,1) primary keys, resolving the R-012/IC-19 concurrency gap for
these three tables.

Deliberately lives here, NOT as a numbered file under migrations/ --
migrations/ is scanned unconditionally by src/lakehouse/migrations.py's
_discover_migrations() and applied against SQLite in tests / Azure SQL in
prod. A T-SQL-only DDL file placed there gets picked up and run against the
wrong backend, colliding with tables that already exist there (confirmed:
this broke the test suite on the first attempt -- fixed by removing that
file and keeping the DDL here instead). This mirrors the existing
src/lakehouse/azure_sql_migrations.py precedent exactly: a one-shot Python
creator with its own TABLES dict, living outside migrations/, not a
numbered .sql file.

This script is also deliberately NOT part of src/lakehouse/connection.py --
it uses its own temporary connection function, pointed at the new SQL
database in Fabric target, so it could run independently of
get_fabric_connection() during the migration (before Stage 4 repointed
get_fabric_connection() itself at this same target). Same auth mechanism as
get_fabric_connection() -- AzureCliCredential + pyodbc access-token
attribute, no interactive/WAM-broker auth -- just a different
server/database.

Safe to re-run: every CREATE TABLE is guarded by a check against
sys.tables, same pattern as src/lakehouse/azure_sql_migrations.py.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import pyodbc
from azure.identity import AzureCliCredential

SQL_COPT_SS_ACCESS_TOKEN = 1256


def get_fabric_sqldb_connection():
    """Temporary, migration-script-only connection to the new SQL database
    in Fabric item. Mirrors get_fabric_connection()'s auth mechanism exactly
    (AzureCliCredential -> pyodbc access-token attribute) but targets
    FABRIC_SQLDB_ENDPOINT/FABRIC_SQLDB_NAME instead of
    FABRIC_SQL_ENDPOINT/FABRIC_WAREHOUSE_NAME. Not added to connection.py --
    that repoint happens in Stage 4, only after Stage 3's row counts are
    confirmed correct."""
    endpoint = os.getenv("FABRIC_SQLDB_ENDPOINT")
    database = os.getenv("FABRIC_SQLDB_NAME")
    tenant_id = os.getenv("FABRIC_TENANT_ID")

    credential = AzureCliCredential(tenant_id=tenant_id)
    token = credential.get_token("https://database.windows.net/.default")
    token_bytes = token.token.encode("utf-16-le")
    token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

    conn_str = (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server={endpoint},1433;"
        f"Database={database};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct})


TABLES = {
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
}


def run():
    conn = get_fabric_sqldb_connection()
    created = []
    try:
        cursor = conn.cursor()
        for table_name, create_sql in TABLES.items():
            cursor.execute("SELECT 1 FROM sys.tables WHERE name = ?", [table_name])
            if cursor.fetchone():
                print(f"{table_name}: already exists, skipped")
                continue
            cursor.execute(create_sql)
            conn.commit()
            created.append(table_name)
            print(f"{table_name}: created")
    finally:
        conn.close()
    return created


if __name__ == "__main__":
    print("Connecting to SQL database in Fabric (Azure CLI token auth)...")
    created = run()
    print(f"Done. Created: {created if created else '(none — all already existed)'}")
