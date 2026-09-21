"""Writes two narrow, typed Delta tables in the Fabric Lakehouse that
together bridge bronze.raw_statement (one big JSON blob per statement) and
dbt -- moved here from research_schema 2026-09-21, see git history for the
migration script:
  - bronze.unnested_statement_lines: one row per LINE
    (statement_id, line_number, extraction_confidence, shop_name)
  - bronze.unnested_statement_fields: one row per LINE-FIELD
    (statement_id, line_number, raw_field_name, raw_field_value)

Why two tables, not one: confirmed 2026-09-18 that write latency to
OneLake scales with how many COLUMNS get written, not row count --
timing the exact same 1280-row Keystone dataset went from 135.7s (11
columns, including vendor_id/vendor_display_name/pdf_file_name/
version_number/ingested_at repeated on every single field-row) down to
6.17s (4 columns) once those were removed. Those statement-level columns
don't need to be repeated anywhere: raw_statement itself already has
vendor_id/vendor_display_name/source_file_name/version_number as small,
individually-cheap-to-read columns -- dbt can read all of it except
raw_payload directly (only raw_payload is the wide column T-SQL can't
read). Line-level fields (extraction_confidence, shop_name) still need
their own small table since they're not on raw_statement's header row,
but keeping THAT separate from the exploded per-field table (rather than
repeating them on every field-row of a line) keeps both tables narrow.

Why this exists at all: confirmed 2026-09-17 that dbt/T-SQL cannot read
raw_statement.raw_payload directly for any statement of real size --
Fabric's SQL surface (Lakehouse SQL analytics endpoint AND the Warehouse
engine itself) currently caps a single column's width at ~8000 chars
(varchar) / ~4000 chars (nvarchar), and a full statement's JSON routinely
exceeds that (confirmed: 17847 chars for a 106-line statement). That's a
genuine platform ceiling on cell width, not a bug in how the SQL was
written. (An earlier version of this pipeline did the whole mapping/
normalization pivot in Python instead, in a module called
silver_silver_build.py -- removed 2026-09-18 once dbt could do that job
directly against these tables; see git history if the full "why Python
first, then back to dbt" story is needed.)

dbt reads both tables plus raw_statement (see
dbt/vive_recon/models/silver_silver/) to do the mapping/normalization
pivot, reusing the macro + seeds already built
(dbt/vive_recon/macros/apply_vendor_normalization.sql,
seeds/vendor_field_mapping.csv, seeds/vendor_normalization_rule.csv).

Written as ONE bulk write_deltalake() call per table per statement
(append), never row-by-row SQL inserts -- confirmed 2026-09-17 that
per-row pyodbc inserts (silver_silver's old approach) get noticeably slow
past a few hundred rows and won't hold up at real volume (200+
statements).

Same auth/connection mechanics as bronze_raw.py (reused, not
reinvented): ClientSecretCredential + write_deltalake against OneLake.
Uses its OWN lock file, not bronze_raw.py's or fabric_dbt_runner.py's
shared one -- this write has nothing to race against those for. Best-
effort: never raises into the caller. Missing Fabric config is a silent
no-op, matching every other write in this pipeline.
"""
import json
import logging
import os

from src.lakehouse.fabric_dbt_runner import fabric_pipeline_lock
from src.lakehouse.bronze_raw import read_raw_statement

logger = logging.getLogger(__name__)

TABLE_URI_SCHEMA = "bronze"
LINES_TABLE_NAME = "unnested_statement_lines"
FIELDS_TABLE_NAME = "unnested_statement_fields"
_LOCK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "dbt", ".bronze_unnest_pipeline.lock"
)


def _fabric_configured() -> bool:
    return bool(
        os.getenv("FABRIC_TENANT_ID")
        and os.getenv("FABRIC_CLIENT_ID")
        and os.getenv("FABRIC_CLIENT_SECRET")
        and os.getenv("FABRIC_WORKSPACE_ID")
        and os.getenv("FABRIC_LAKEHOUSE_ID")
    )


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


def _explode(wrapped_lines: list, statement_id: str):
    """Given a list already in the {"_raw_row": ..., "_extraction_confidence":
    ..., "_shop_name": ...} shape (see bronze_raw.py's write_raw_statement()
    docstring for where that shape comes from), returns (line_rows,
    field_rows) -- deliberately NO statement-level columns (vendor_id etc.)
    on either; see this module's docstring for why. A line missing
    `_raw_row` (or one that isn't a dict) contributes no field rows, but
    still gets a line row (confidence/shop may still be meaningful even if
    the raw dict itself was empty) -- not an error either way."""
    line_rows = []
    field_rows = []
    for line_number, wrapped in enumerate(wrapped_lines):
        if not isinstance(wrapped, dict):
            continue
        raw_row = wrapped.get("_raw_row")
        extraction_confidence = wrapped.get("_extraction_confidence")
        shop_name = wrapped.get("_shop_name")

        line_rows.append({
            "statement_id": statement_id,
            "line_number": line_number,
            "extraction_confidence": extraction_confidence,
            "shop_name": shop_name,
        })

        if isinstance(raw_row, dict):
            for raw_field_name, raw_value in raw_row.items():
                field_rows.append({
                    "statement_id": statement_id,
                    "line_number": line_number,
                    "raw_field_name": raw_field_name,
                    "raw_field_value": None if raw_value is None else str(raw_value),
                })

    return line_rows, field_rows


def _write_bulk(table_name: str, rows: list, string_cols: list, int_cols: list, float_cols: list) -> int:
    """Bulk-writes rows in ONE write_deltalake() call -- never row-by-row.
    Returns the row count written, 0 if there's nothing to write, Fabric
    isn't configured, or the write failed (all non-fatal)."""
    if not rows:
        return 0
    if not _fabric_configured():
        logger.debug("Fabric not configured -- skipping %s write", table_name)
        return 0

    try:
        import pandas as pd
        from deltalake import write_deltalake

        df = pd.DataFrame(rows)
        for col in string_cols:
            df[col] = df[col].astype("string")
        for col in int_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
        for col in float_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        table_uri = _table_uri(table_name)
        with fabric_pipeline_lock(lock_path=_LOCK_PATH):
            write_deltalake(
                table_uri, df, mode="append", schema_mode="merge",
                storage_options=_storage_options(),
            )

        return len(rows)

    except Exception:
        logger.exception("%s write failed (non-fatal)", table_name)
        return 0


def _write_lines_and_fields(line_rows: list, field_rows: list) -> tuple:
    lines_written = _write_bulk(
        LINES_TABLE_NAME, line_rows,
        string_cols=["statement_id", "shop_name"],
        int_cols=["line_number"],
        float_cols=["extraction_confidence"],
    )
    fields_written = _write_bulk(
        FIELDS_TABLE_NAME, field_rows,
        string_cols=["statement_id", "raw_field_name", "raw_field_value"],
        int_cols=["line_number"],
        float_cols=[],
    )
    return lines_written, fields_written


def write_unnested_from_invoices(invoices: list, statement_id: str) -> tuple:
    """The automatic-pipeline entry point -- builds directly from the SAME
    in-memory `invoices` list write_raw_statement() was just given, no
    read-back involved. Returns (lines_written, fields_written)."""
    wrapped_lines = [
        {
            "_raw_row": inv.get("_raw_row"),
            "_extraction_confidence": inv.get("line_confidence"),
            "_shop_name": inv.get("shop"),
        }
        for inv in invoices
    ]
    line_rows, field_rows = _explode(wrapped_lines, statement_id)
    return _write_lines_and_fields(line_rows, field_rows)


def wait_for_visibility(statement_id: str, expected_lines: int, expected_fields: int,
                         timeout_seconds: int = 240, poll_interval: float = 5.0) -> bool:
    """Polls the Lakehouse SQL analytics endpoint until raw_statement,
    unnested_statement_lines, and unnested_statement_fields all show this
    statement_id's data -- the read-after-write race dbt's queries would
    otherwise hit. Confirmed real 2026-09-18: a dbt run triggered
    immediately after a fresh staging write returned 0 rows, silently, no
    error -- the SQL endpoint's propagation lag applies to every table
    here, not just raw_payload's width problem. Polling for the actual
    expected count (rather than a blind fixed delay) means this returns
    as soon as the data is genuinely visible, and gives up cleanly rather
    than guessing at "how long is long enough" if something is actually
    wrong.

    Returns True once all three are visible with at least the expected
    counts, False if timeout_seconds elapses first (caller should treat
    False as "skip this dbt run" -- better than triggering it against
    data that isn't there yet). Never raises: a transient query failure
    during polling is treated the same as "not visible yet.\""""
    if expected_lines <= 0 and expected_fields <= 0:
        return False

    from src.lakehouse.fabric_sql import get_lakehouse_connection
    import time

    deadline = time.time() + timeout_seconds
    while True:
        try:
            conn = get_lakehouse_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM bronze.raw_statement WHERE statement_id = ?", [statement_id])
            raw_ok = cur.fetchone()[0] >= 1
            cur.execute("SELECT COUNT(*) FROM bronze.unnested_statement_lines WHERE statement_id = ?", [statement_id])
            lines_ok = cur.fetchone()[0] >= expected_lines
            cur.execute("SELECT COUNT(*) FROM bronze.unnested_statement_fields WHERE statement_id = ?", [statement_id])
            fields_ok = cur.fetchone()[0] >= expected_fields
            if raw_ok and lines_ok and fields_ok:
                return True
        except Exception:
            logger.debug("wait_for_visibility query failed for statement_id=%s (treated as not-yet-visible)", statement_id, exc_info=True)

        if time.time() >= deadline:
            return False
        time.sleep(poll_interval)


def write_unnested_from_storage(statement_id: str) -> tuple:
    """Rebuild utility, NOT used by the automatic pipeline path -- reads
    bronze.raw_statement back out (direct Delta read, see
    read_raw_statement()'s docstring) and explodes it the same way. Useful
    for backfilling or rebuilding a statement without re-running
    extraction. Returns (0, 0) if the statement can't be read."""
    raw_statement = read_raw_statement(statement_id)
    if not raw_statement:
        logger.warning("No bronze.raw_statement row found for statement_id=%s", statement_id)
        return (0, 0)

    try:
        wrapped_lines = json.loads(raw_statement.get("raw_payload") or "[]")
    except (TypeError, ValueError):
        logger.exception("raw_payload for statement_id=%s is not valid JSON", statement_id)
        return (0, 0)

    line_rows, field_rows = _explode(wrapped_lines, statement_id)
    return _write_lines_and_fields(line_rows, field_rows)
