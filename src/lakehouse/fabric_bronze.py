"""Writes Bronze rows to the Fabric Lakehouse, in addition to (never instead
of) notebooks/01_document_intake.py's write_to_bronze() writing to
bronze_vendor_statement_raw. Same call site, same inputs, same row shape --
this only decides where else a copy of the same data goes.

One Delta table per vendor (bronze.bronze_<vendor_id>_raw) in the Lakehouse,
all sharing the same columns -- extraction (both the AI engine's
VISION_PROMPT and the deterministic python-library adapter's _FIELD_MAP)
already normalizes every vendor into this one generic shape before it
reaches write_to_bronze(), so there's no vendor-specific raw layout left to
preserve here; "different table per vendor" is a partitioning choice, not a
schema difference.

Best-effort: never raises into the caller. Missing Fabric config (no
FABRIC_CLIENT_ID/SECRET in .env -- the common case for local dev/tests) is
a silent no-op, not an error, since this write is additive, not required
for the existing pipeline to function.
"""
import logging
import os
import re
import struct
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _fabric_configured() -> bool:
    return bool(
        os.getenv("FABRIC_TENANT_ID")
        and os.getenv("FABRIC_CLIENT_ID")
        and os.getenv("FABRIC_CLIENT_SECRET")
        and os.getenv("FABRIC_WORKSPACE_ID")
        and os.getenv("FABRIC_LAKEHOUSE_ID")
        and os.getenv("FABRIC_SQL_ENDPOINT_ID")
    )


def _get_credential():
    from azure.identity import ClientSecretCredential

    return ClientSecretCredential(
        tenant_id=os.environ["FABRIC_TENANT_ID"],
        client_id=os.environ["FABRIC_CLIENT_ID"],
        client_secret=os.environ["FABRIC_CLIENT_SECRET"],
    )


def _table_uri(vendor_id: str) -> str:
    workspace_id = os.environ["FABRIC_WORKSPACE_ID"]
    lakehouse_id = os.environ["FABRIC_LAKEHOUSE_ID"]
    return (
        f"abfss://{workspace_id}@onelake.dfs.fabric.microsoft.com/"
        f"{lakehouse_id}/Tables/bronze/{_table_name(vendor_id)}"
    )


def _storage_options() -> dict:
    return {
        "azure_tenant_id": os.environ["FABRIC_TENANT_ID"],
        "azure_client_id": os.environ["FABRIC_CLIENT_ID"],
        "azure_client_secret": os.environ["FABRIC_CLIENT_SECRET"],
        "use_fabric_endpoint": "true",
    }


def _refresh_sql_endpoint_metadata() -> None:
    """Forces the SQL analytics endpoint to pick up a schema change (new
    table, new column) immediately rather than waiting on background sync,
    which can lag by tens of seconds on this workspace's (legacy) metadata
    sync -- see dbt/README.md's Phase 1 notes for how this was diagnosed.
    Best-effort: a failure here just means dbt's next run might hit a
    transient "invalid column name" until sync catches up on its own.
    """
    try:
        import requests

        token = _get_credential().get_token("https://api.fabric.microsoft.com/.default").token
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
        logger.exception("Fabric SQL endpoint metadata refresh failed (non-fatal)")


def _table_name(vendor_id: str) -> str:
    slug = re.sub(r"[^a-z0-9_]", "_", vendor_id.strip().lower())
    return f"bronze_{slug}_raw"


def _wait_for_row_visibility(vendor_id: str, statement_id: str, expected_count: int,
                              timeout_seconds: int = 45, poll_interval_seconds: int = 3) -> bool:
    """Polls the SQL analytics endpoint until it can see all `expected_count`
    just-written rows for this statement, or times out. Without this, a
    caller that triggers `dbt run` immediately after write_bronze_fabric()
    returns can race the metadata sync -- dbt's query silently sees 0 rows
    for a not-yet-synced statement (not an error, just an empty MERGE
    source), leaving silver.statement_line missing that statement's rows
    even though silver.statement (whose GROUP BY still produces a row from
    whatever partial data *is* visible) looks fine. Confirmed happening in
    practice: bronze had all rows correctly, a manual `dbt run` minutes
    later picked them up cleanly, but the automatic run right after the
    write had produced zero statement_line rows for that statement.
    Best-effort: returns False (not raised) on timeout or any error --
    the caller proceeds regardless, same as every other failure mode here.
    """
    try:
        import pyodbc

        table = _table_name(vendor_id)
        token = _get_credential().get_token("https://database.windows.net/.default")
        token_bytes = token.token.encode("utf-16-le")
        token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)
        conn_str = (
            "Driver={ODBC Driver 18 for SQL Server};"
            f"Server={os.environ['FABRIC_SQL_ENDPOINT']},1433;"
            f"Database={os.environ['FABRIC_LAKEHOUSE_NAME']};"
            "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        )
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                conn = pyodbc.connect(conn_str, attrs_before={1256: token_struct})
                cur = conn.cursor()
                cur.execute(
                    f"SELECT COUNT(*) FROM [bronze].[{table}] WHERE statement_id = ?",
                    [statement_id],
                )
                if cur.fetchone()[0] >= expected_count:
                    return True
            except Exception:
                pass  # table/column not visible yet -- keep polling until the deadline
            time.sleep(poll_interval_seconds)
        logger.warning(
            "Fabric SQL endpoint didn't show all %d row(s) for vendor_id=%s "
            "statement_id=%s within %ds -- a Silver build triggered immediately "
            "after this may miss them",
            expected_count, vendor_id, statement_id, timeout_seconds,
        )
        return False
    except Exception:
        logger.exception("Row-visibility wait failed to start (non-fatal)")
        return False


def write_bronze_fabric(invoices: list, schema_result: dict, statement_id: str,
                         pdf_path: str, statement_period: str, vendor_id: str,
                         version_info: dict = None) -> int:
    """Mirrors write_to_bronze()'s exact signature and row shape (same
    fields, same fallback logic for amount/outstanding_amount and
    credit) -- writes the same data into
    bronze.bronze_<vendor_id>_raw in the Fabric Lakehouse. Returns count of
    rows written, 0 if Fabric isn't configured or the write failed (both
    non-fatal to the caller).
    """
    if not invoices:
        return 0
    if not _fabric_configured():
        logger.debug("Fabric not configured -- skipping Fabric Bronze write")
        return 0

    try:
        import pandas as pd
        from deltalake import write_deltalake

        version_info = version_info or {
            "version_number": 1,
            "previous_statement_id": None,
            "is_latest_version": 1,
        }
        now = datetime.now(timezone.utc)
        source_file = os.path.basename(pdf_path)
        vendor_name = schema_result.get("vendor_metadata", {}).get("vendor_name")
        provider_used = schema_result.get("_provider_used", "unknown")
        model_used = schema_result.get("_model_used", "")
        currency = schema_result.get("statement_metadata", {}).get("currency")
        default_shop = (schema_result.get("vendor_metadata", {}).get("shop_or_entity") or [None])[0]

        rows = []
        for inv in invoices:
            amount = inv.get("amount") if inv.get("amount") is not None else inv.get("outstanding_amount")
            outstanding = inv.get("outstanding_amount") if inv.get("outstanding_amount") is not None else inv.get("amount")
            rows.append({
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "source_file": source_file,
                "statement_id": statement_id,
                "statement_period": statement_period,
                "page_number": inv.get("page_number"),
                "row_number": inv.get("row_number"),
                "ingestion_timestamp": now,
                "raw_invoice_number": inv.get("invoice_number"),
                "raw_invoice_date": inv.get("invoice_date"),
                "raw_due_date": inv.get("due_date"),
                "raw_amount": amount,
                "raw_outstanding_amount": outstanding,
                "raw_ro_number": inv.get("ro_number"),
                "raw_po_number": inv.get("po_number"),
                "raw_work_order_number": inv.get("work_order_number"),
                "raw_description": inv.get("description"),
                "raw_credit": inv.get("credit"),
                "raw_shop_name": inv.get("shop") or default_shop,
                "raw_currency": currency,
                "extraction_confidence": inv.get("line_confidence"),
                "extraction_model": f"{provider_used}/{model_used}",
                "raw_charges": inv.get("charges"),
                "raw_credits": inv.get("credits"),
                "raw_amount_due": inv.get("amount_due"),
                "raw_transaction_code": inv.get("transaction_code"),
                "raw_balance_forward": inv.get("balance_forward"),
                "raw_period_activity": inv.get("period_activity"),
                "raw_credit_applied": inv.get("credit_applied"),
                "raw_payment_applied": inv.get("payment_applied"),
                "version_number": version_info["version_number"],
                "previous_statement_id": version_info["previous_statement_id"],
                "is_latest_version": version_info["is_latest_version"],
            })

        df = pd.DataFrame(rows)

        # A 100%-null column gets an ambiguous dtype the SQL analytics
        # endpoint won't expose as a queryable column, even though it's
        # present in the Delta schema -- force concrete types regardless of
        # whether this particular statement populated them. See
        # dbt/README.md's Phase 1 notes for how this was diagnosed.
        numeric_cols = [
            "raw_amount", "raw_outstanding_amount", "raw_credit",
            "extraction_confidence", "raw_charges", "raw_credits",
            "raw_amount_due", "raw_balance_forward", "raw_period_activity",
            "raw_credit_applied", "raw_payment_applied",
        ]
        for c in numeric_cols:
            df[c] = pd.to_numeric(df[c], errors="coerce")

        date_cols = ["raw_invoice_date", "raw_due_date"]
        for c in date_cols:
            df[c] = pd.to_datetime(df[c], errors="coerce")

        string_cols = [
            "vendor_id", "vendor_name", "source_file", "statement_id",
            "statement_period", "raw_invoice_number", "raw_ro_number",
            "raw_po_number", "raw_work_order_number", "raw_description",
            "raw_shop_name", "raw_currency", "extraction_model",
            "raw_transaction_code", "previous_statement_id",
        ]
        for c in string_cols:
            df[c] = df[c].astype("string")

        table_uri = _table_uri(vendor_id)
        write_deltalake(
            table_uri, df, mode="append", schema_mode="merge",
            storage_options=_storage_options(),
        )

        # Always refresh -- cheap (a few seconds), and a new statement can
        # still be the first to populate a previously-all-null column even
        # on an existing table (schema_mode="merge" allows that silently).
        _refresh_sql_endpoint_metadata()

        # Block here (not in the caller) until the SQL endpoint can actually
        # see these rows -- a dbt Silver build triggered right after this
        # returns must not race the metadata sync. See
        # _wait_for_row_visibility()'s docstring for how this was found.
        _wait_for_row_visibility(vendor_id, statement_id, len(rows))

        return len(rows)

    except Exception:
        logger.exception(
            "Fabric Bronze write failed for vendor_id=%s statement_id=%s (non-fatal, "
            "existing bronze_vendor_statement_raw write is unaffected)",
            vendor_id, statement_id,
        )
        return 0
