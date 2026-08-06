"""One-time data migration: copies existing rows from the three
Fabric-Warehouse-cut-over tables (extraction_cache, document_intake_log,
validation_document_review_queue) to the new SQL database in Fabric item.

Reads from the OLD target via get_fabric_connection() (unchanged --
still points at Fabric Warehouse until Stage 4 repoints it). Writes to the
NEW target via get_fabric_sqldb_connection() (scripts/create_fabric_sqldb_schema.py's
temporary connection function -- same AzureCliCredential auth mechanism,
different server/database).

Old `id` values are NOT preserved -- the new tables' IDENTITY columns
assign fresh ids on insert. Confirmed safe before writing this script: no
FOREIGN KEY (enforced or by-convention) anywhere in this codebase references
these three tables' id columns (grepped migrations/*.sql and src/ -- this
codebase does not use enforced FOREIGN KEY constraints anywhere; the one
by-convention link found, exception_dispositions -> gold_exceptions, is
unrelated to these three tables).

Does NOT drop, truncate, or modify the old Warehouse tables -- read-only
against the old target. Safe to re-run against an empty new table; will
duplicate rows if re-run after a successful migration (not idempotent by
design -- this is a one-time script, not a numbered migration).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from src.lakehouse.connection import get_fabric_connection
from create_fabric_sqldb_schema import get_fabric_sqldb_connection

TABLE_COLUMNS = {
    "extraction_cache": [
        "document_hash", "statement_id", "source_file",
        "extraction_method", "row_count", "ingestion_timestamp",
    ],
    "document_intake_log": [
        "document_id", "document_hash", "source_file", "ingestion_timestamp",
        "document_type", "document_type_confidence", "vendor_name",
        "shop_or_entity", "statement_date", "statement_period", "currency",
        "statement_total_as_printed", "extraction_confidence_overall",
        "extraction_model", "extraction_method", "routing_decision",
        "statement_id", "invoice_count", "warnings", "schema_version",
        "blob_storage_path", "original_filename", "uploaded_by", "uploaded_at",
    ],
    "validation_document_review_queue": [
        "review_id", "vendor_id", "source_file", "statement_id",
        "statement_period", "pipeline_stage", "rejection_category",
        "rejection_details", "extraction_confidence",
        "confidence_threshold_applied", "raw_payload", "review_status",
        "flagged_timestamp", "reviewed_by", "reviewed_timestamp",
        "resolution_notes",
    ],
}


def migrate_table(old_conn, new_conn, table_name, columns):
    old_cursor = old_conn.cursor()
    old_cursor.execute(f"SELECT {', '.join(columns)} FROM {table_name} ORDER BY id")
    rows = old_cursor.fetchall()

    if not rows:
        return 0

    placeholders = ", ".join(["?"] * len(columns))
    insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"

    new_cursor = new_conn.cursor()
    for row in rows:
        new_cursor.execute(insert_sql, list(row))
    new_conn.commit()

    return len(rows)


def main():
    old_conn = get_fabric_connection()
    new_conn = get_fabric_sqldb_connection()
    try:
        for table_name, columns in TABLE_COLUMNS.items():
            count = migrate_table(old_conn, new_conn, table_name, columns)
            print(f"{table_name}: migrated {count} rows")
    finally:
        old_conn.close()
        new_conn.close()


if __name__ == "__main__":
    main()
