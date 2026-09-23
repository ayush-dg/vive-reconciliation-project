"""One-shot creator for the 3 Bronze Delta tables in a Fabric Lakehouse
(bronze.raw_statement, bronze.unnested_statement_lines,
bronze.unnested_statement_fields).

These tables are normally never explicitly created -- src/lakehouse/
bronze_raw.py's write_raw_statement() and bronze_unnest.py's
write_unnested_from_invoices() call write_deltalake(mode="append",
schema_mode="merge"), which auto-creates the table from the DataFrame's
own schema on first write. Both early-return without writing anything if
given an empty invoices list, so there's no organic way to pre-create an
empty table by running the app's real code path against zero rows -- this
script does the same write_deltalake() call directly, with an explicitly
empty (0-row) DataFrame carrying the exact same dtypes those two modules
use, so a brand-new environment gets the correct schema before any real
job has ever run.

Column dtypes here are copied 1:1 from bronze_raw.py's write_raw_statement()
and bronze_unnest.py's _write_bulk() astype() calls -- keep them in sync if
those change.

Safe to re-run: write_deltalake(mode="append") on an already-existing table
just appends nothing when the DataFrame is empty.

Usage: venv/Scripts/python.exe scripts/create_fabric_lakehouse_schema.py
Requires FABRIC_TENANT_ID, FABRIC_CLIENT_ID, FABRIC_CLIENT_SECRET,
FABRIC_WORKSPACE_ID, FABRIC_LAKEHOUSE_ID in the environment (pass
prod values inline rather than relying on .env when targeting prod).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import pandas as pd
from deltalake import write_deltalake

TABLE_URI_SCHEMA = "bronze"


def _table_uri(table_name: str) -> str:
    workspace_id = os.environ["FABRIC_WORKSPACE_ID"]
    lakehouse_id = os.environ["FABRIC_LAKEHOUSE_ID"]
    return (
        f"abfss://{workspace_id}@onelake.dfs.fabric.microsoft.com/"
        f"{lakehouse_id}/Tables/{TABLE_URI_SCHEMA}/{table_name}"
    )


def _storage_options() -> dict:
    return {
        "azure_tenant_id": os.environ["FABRIC_TENANT_ID"],
        "azure_client_id": os.environ["FABRIC_CLIENT_ID"],
        "azure_client_secret": os.environ["FABRIC_CLIENT_SECRET"],
        "use_fabric_endpoint": "true",
    }


def _create_empty(table_name: str, df: pd.DataFrame) -> None:
    write_deltalake(
        _table_uri(table_name), df, mode="append", schema_mode="merge",
        storage_options=_storage_options(),
    )
    print(f"created (or confirmed) bronze.{table_name}, columns: {list(df.columns)}")


def main():
    raw_statement = pd.DataFrame({
        "vendor_id": pd.Series(dtype="string"),
        "vendor_display_name": pd.Series(dtype="string"),
        "statement_id": pd.Series(dtype="string"),
        "source_file_name": pd.Series(dtype="string"),
        "ingestion_timestamp": pd.Series(dtype="datetime64[ns, UTC]"),
        "extraction_engine": pd.Series(dtype="string"),
        "invoice_count": pd.Series(dtype="float64"),
        "version_number": pd.Series(dtype="float64"),
        "raw_payload": pd.Series(dtype="string"),
    })
    _create_empty("raw_statement", raw_statement)

    unnested_statement_lines = pd.DataFrame({
        "statement_id": pd.Series(dtype="string"),
        "line_number": pd.Series(dtype="Int64"),
        "extraction_confidence": pd.Series(dtype="float64"),
        "shop_name": pd.Series(dtype="string"),
    })
    _create_empty("unnested_statement_lines", unnested_statement_lines)

    unnested_statement_fields = pd.DataFrame({
        "statement_id": pd.Series(dtype="string"),
        "line_number": pd.Series(dtype="Int64"),
        "raw_field_name": pd.Series(dtype="string"),
        "raw_field_value": pd.Series(dtype="string"),
    })
    _create_empty("unnested_statement_fields", unnested_statement_fields)


if __name__ == "__main__":
    main()
