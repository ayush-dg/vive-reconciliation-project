"""Writes a raw, pre-mapping dump of one extracted PDF to a single shared
Fabric Lakehouse table, bronze.raw_statement -- moved here from
research_schema.raw_statement 2026-09-21 (see git history for the
migration script) now that it's this pipeline's actual Bronze layer, not a
side research artifact. It exists so a human can inspect what extraction
actually produced before any column-mapping/validation logic touched it,
and is what dbt/vive_recon/models/silver/statement*.sql read from.

One row per PDF/statement, not per line -- raw_payload is a JSON array
holding every extracted line's own raw (pre-mapping) row. Each invoice
dict passed in is expected to carry an `_raw_row` key (the model's own
JSON for AI-routed rows -- see claude_sonnet_client.py's
_parse_invoice_row(); the per-vendor extractor module's own field dict for
pdfplumber-routed rows -- see adapter.py) holding whatever the extractor
produced before mapping collapsed it to the fixed invoice schema. A line
missing `_raw_row` still lands in the array as null, rather than being
dropped -- silently losing lines here would defeat the point of a raw dump.

Same auth/connection mechanics as fabric_bronze.py (reused, not
reinvented): ClientSecretCredential + write_deltalake against OneLake.
Uses its OWN lock file (_LOCK_PATH below), not the shared
fabric_pipeline_lock() Bronze/dbt/matching use -- this write has nothing
to do with those and, in RESEARCH_MODE_EXTRACTION_ONLY, none of them even
run, so there's no reason to queue behind them. Confirmed 2026-09-15:
sharing that lock across a 336-PDF batch made later jobs queue past its
300s timeout and silently lose their raw-dump write. Best-effort: never
raises into the caller. Missing Fabric config is a silent no-op.
"""
import json
import logging
import os
from datetime import datetime, timezone

from src.lakehouse.fabric_dbt_runner import fabric_pipeline_lock

logger = logging.getLogger(__name__)

TABLE_URI_SCHEMA = "bronze"
TABLE_NAME = "raw_statement"
_LOCK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "dbt", ".bronze_raw_pipeline.lock"
)


def _fabric_configured() -> bool:
    return bool(
        os.getenv("FABRIC_TENANT_ID")
        and os.getenv("FABRIC_CLIENT_ID")
        and os.getenv("FABRIC_CLIENT_SECRET")
        and os.getenv("FABRIC_WORKSPACE_ID")
        and os.getenv("FABRIC_LAKEHOUSE_ID")
    )


def _table_uri() -> str:
    workspace_id = os.environ["FABRIC_WORKSPACE_ID"]
    lakehouse_id = os.environ["FABRIC_LAKEHOUSE_ID"]
    return (
        f"abfss://{workspace_id}@onelake.dfs.fabric.microsoft.com/"
        f"{lakehouse_id}/Tables/{TABLE_URI_SCHEMA}/{TABLE_NAME}"
    )


def _storage_options() -> dict:
    return {
        "azure_tenant_id": os.environ["FABRIC_TENANT_ID"],
        "azure_client_id": os.environ["FABRIC_CLIENT_ID"],
        "azure_client_secret": os.environ["FABRIC_CLIENT_SECRET"],
        "use_fabric_endpoint": "true",
    }


def _refresh_sql_endpoint_metadata() -> None:
    """Same forced-refresh fabric_bronze.py uses -- without it, a brand-new
    schema/table can sit invisible to the SQL analytics endpoint well past
    the tens-of-seconds background sync window (confirmed: still not
    visible after 30s without this call). NOT called from write_raw_statement()
    itself anymore (2026-09-15) -- it's a ~30s-capable network round-trip
    that isn't required for the write to succeed, only for how soon a human
    querying via SQL sees it, and calling it once per PDF across a large
    batch was the main thing making each write slow enough to cause lock
    pile-up. Call this manually after a batch if you want the table visible
    right away; otherwise the SQL endpoint's own background sync catches up
    within its usual window. Best-effort, non-fatal."""
    try:
        import requests
        from azure.identity import ClientSecretCredential

        credential = ClientSecretCredential(
            tenant_id=os.environ["FABRIC_TENANT_ID"],
            client_id=os.environ["FABRIC_CLIENT_ID"],
            client_secret=os.environ["FABRIC_CLIENT_SECRET"],
        )
        token = credential.get_token("https://api.fabric.microsoft.com/.default").token
        workspace_id = os.environ["FABRIC_WORKSPACE_ID"]
        sql_endpoint_id = os.environ["FABRIC_SQL_ENDPOINT_ID"]
        requests.post(
            f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}"
            f"/sqlEndpoints/{sql_endpoint_id}/refreshMetadata",
            headers={"Authorization": f"Bearer {token}"},
            json={},
            timeout=30,
        )
    except Exception:
        logger.exception("Research schema SQL endpoint metadata refresh failed (non-fatal)")


def write_raw_statement(invoices: list, vendor_id: str, statement_id: str,
                         source_file_name: str, extraction_engine: str,
                         vendor_display_name: str = None,
                         version_number: int = None) -> int:
    """Appends exactly one row for this PDF/statement to
    bronze.raw_statement -- raw_payload is a JSON array of every
    line's raw (pre-mapping) row, each wrapped as {"_raw_row": ...,
    "_extraction_confidence": ..., "_shop_name": ...} rather than the bare
    _raw_row dict -- _extraction_confidence/_shop_name come from each
    invoice's own `line_confidence`/`shop` keys, the same source
    fabric_bronze.py's write_bronze_fabric() already pulls its
    extraction_confidence/raw_shop_name bronze columns from (see that
    module for the exact `inv.get(...)` calls) -- not persisted here
    before now, so silver_silver's line_type/vendor_group_label/
    extraction_confidence columns had nowhere to read them from.

    vendor_display_name is the alias-resolved label from
    src/vendor_identity.py:display_name() -- purely for human readability
    in this raw dump; it is NOT used for identity/routing anywhere
    (vendor_id remains the canonical key, same as everywhere else in this
    app). version_number is the same per-statement version_info already
    resolved by the caller (resolve_version_info()) before this is called.

    Returns 1 if written, 0 if Fabric isn't configured, there's nothing to
    write, or the write failed (all non-fatal to the caller)."""
    if not invoices:
        return 0
    if not _fabric_configured():
        logger.debug("Fabric not configured -- skipping research raw-statement write")
        return 0

    try:
        import pandas as pd
        from deltalake import write_deltalake

        now = datetime.now(timezone.utc)
        raw_rows = [
            {
                "_raw_row": inv.get("_raw_row"),
                "_extraction_confidence": inv.get("line_confidence"),
                "_shop_name": inv.get("shop"),
            }
            for inv in invoices
        ]

        row = {
            "vendor_id": vendor_id,
            "vendor_display_name": vendor_display_name,
            "statement_id": statement_id,
            "source_file_name": source_file_name,
            "ingestion_timestamp": now,
            "extraction_engine": extraction_engine,
            "invoice_count": len(invoices),
            "version_number": version_number,
            "raw_payload": json.dumps(raw_rows, default=str),
        }

        df = pd.DataFrame([row])
        df["vendor_id"] = df["vendor_id"].astype("string")
        df["vendor_display_name"] = df["vendor_display_name"].astype("string")
        df["statement_id"] = df["statement_id"].astype("string")
        df["source_file_name"] = df["source_file_name"].astype("string")
        df["extraction_engine"] = df["extraction_engine"].astype("string")
        df["raw_payload"] = df["raw_payload"].astype("string")
        df["invoice_count"] = pd.to_numeric(df["invoice_count"], errors="coerce")
        df["version_number"] = pd.to_numeric(df["version_number"], errors="coerce")

        table_uri = _table_uri()
        with fabric_pipeline_lock(lock_path=_LOCK_PATH):
            write_deltalake(
                table_uri, df, mode="append", schema_mode="merge",
                storage_options=_storage_options(),
            )

        return 1

    except Exception:
        logger.exception(
            "Research raw-statement write failed for vendor_id=%s statement_id=%s (non-fatal)",
            vendor_id, statement_id,
        )
        return 0


def read_raw_statement(statement_id: str) -> dict:
    """Reads one row of bronze.raw_statement DIRECTLY from the
    Delta Lake files (via the deltalake package), NOT through the Fabric
    SQL analytics endpoint -- confirmed 2026-09-17 that the SQL endpoint
    silently truncates this table's raw_payload column at 8000 characters
    (LEN() via T-SQL returned 8000 for a row whose real value, read this
    same way, was 17847 chars). Any statement with more than a modest
    number of invoice lines exceeds that, so anything needing raw_payload
    -- currently src/lakehouse/bronze_unnest.py's rebuild-from-storage
    path -- reads it only through this function, never via OPENJSON/T-SQL.

    Returns None if Fabric isn't configured, the table can't be read, or
    no row matches statement_id (never raises -- same "additive, never
    blocks the pipeline" philosophy as write_raw_statement())."""
    if not _fabric_configured():
        return None
    try:
        from deltalake import DeltaTable

        dt = DeltaTable(_table_uri(), storage_options=_storage_options())
        df = dt.to_pandas()
        matches = df[df["statement_id"] == statement_id]
        if matches.empty:
            return None
        # "Latest wins" must be by ingestion_timestamp, not row position --
        # confirmed 2026-09-17 that to_pandas() does NOT return rows in
        # write order (a re-run's freshly-appended row came back BEFORE the
        # original one), so a bare .iloc[-1] silently picked the stale row.
        return matches.sort_values("ingestion_timestamp").iloc[-1].to_dict()
    except Exception:
        logger.exception("Reading raw_statement for statement_id=%s failed (non-fatal)", statement_id)
        return None
