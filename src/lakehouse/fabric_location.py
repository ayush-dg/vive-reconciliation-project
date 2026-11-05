"""Copies a statement's location from Azure SQL into Fabric.

The location is written into bronze.raw_statement and silver.statement when a
statement is processed. A later change -- a statement taking the shop of its
matched NetSuite bills (src/validation/invoice_location.py) -- is made in Azure
SQL first; sync_statement_location() then brings Fabric in line, bronze first
(silver is built from it), then silver.statement.

Not called from inside the matching run: bronze is changed under
fabric_pipeline_lock(), which that run can already hold. The callers run it
after the lock is released (the end of scripts/run_full_pipeline.py) or off the
request (sync_in_background(), for a manual match or its undo). Best-effort:
a failure is logged, never raised, and the next sync repairs it.
"""
import logging
import threading

from src.lakehouse.connection import execute_query
from src.validation.shop_list import LOCATION_COLUMNS

logger = logging.getLogger(__name__)


def _literal(value) -> str:
    """A Delta SQL string literal, for the update expression."""
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


def _azure_values(statement_id: str):
    """The location columns of the statement's newest row in Azure SQL, or None."""
    rows = execute_query(
        f"SELECT id, {', '.join(LOCATION_COLUMNS)} FROM document_intake_log WHERE statement_id = ?", [statement_id])
    if not rows:
        return None
    newest = max(rows, key=lambda row: row["id"])
    return {column: newest.get(column) for column in LOCATION_COLUMNS}


def _silver_values(cur, statement_id: str):
    """What silver.statement holds for the statement, or None when it has no row."""
    cur.execute(f"SELECT {', '.join(LOCATION_COLUMNS)} FROM silver.statement WHERE statement_id = ?", [statement_id])
    row = cur.fetchone()
    return dict(zip(LOCATION_COLUMNS, row)) if row else None


def _update_bronze(statement_id: str, values: dict) -> None:
    from deltalake import DeltaTable
    from src.lakehouse.bronze_raw import _storage_options, _table_uri
    from src.lakehouse.fabric_dbt_runner import fabric_pipeline_lock

    with fabric_pipeline_lock():
        DeltaTable(_table_uri(), storage_options=_storage_options()).update(
            predicate=f"statement_id = {_literal(statement_id)}",
            updates={column: _literal(values[column]) for column in LOCATION_COLUMNS})


def _update_silver(conn, cur, statement_id: str, values: dict) -> None:
    cur.execute(
        f"UPDATE silver.statement SET {', '.join(f'{column} = ?' for column in LOCATION_COLUMNS)} WHERE statement_id = ?",
        [values[column] for column in LOCATION_COLUMNS] + [statement_id])
    conn.commit()


def sync_statement_location(statement_id: str) -> bool:
    """Makes bronze.raw_statement and silver.statement hold the location Azure
    SQL has for this statement. True when Fabric was changed; False when it
    already agrees, the statement is not in silver yet (its build reads
    bronze), Fabric is not configured, or anything failed."""
    from src.lakehouse.bronze_raw import _fabric_configured
    from src.lakehouse.fabric_sql import get_warehouse_connection

    if not statement_id or not _fabric_configured():
        return False
    try:
        wanted = _azure_values(statement_id)
        if not wanted:
            return False
        conn = get_warehouse_connection()
        try:
            cur = conn.cursor()
            current = _silver_values(cur, statement_id)
            if current is None or current == wanted:
                return False
            _update_bronze(statement_id, wanted)
            _update_silver(conn, cur, statement_id, wanted)
        finally:
            conn.close()
        logger.info("Fabric location for %s set to %r", statement_id, wanted["billing_location"])
        return True
    except Exception:
        logger.exception("copying the location of %s to Fabric failed (non-fatal)", statement_id)
        return False


MERGE_ATTEMPTS = 3
SILVER_COMMIT_EVERY = 200


def _azure_values_by_statement(statement_ids=None) -> dict:
    """{statement_id: location columns} of each statement's newest Azure SQL
    row; every statement, or just `statement_ids`."""
    rows = execute_query(f"SELECT id, statement_id, {', '.join(LOCATION_COLUMNS)} FROM document_intake_log "
                         "WHERE statement_id IS NOT NULL")
    wanted = set(statement_ids) if statement_ids is not None else None
    newest = {}
    for row in rows:
        sid = row["statement_id"]
        if (wanted is None or sid in wanted) and (sid not in newest or row["id"] > newest[sid]["id"]):
            newest[sid] = row
    return {sid: {column: row.get(column) for column in LOCATION_COLUMNS} for sid, row in newest.items()}


def plan_sync(statement_ids=None) -> dict:
    """{statement_id: location} for the statements whose silver.statement row
    differs from Azure SQL: one read of each, however many statements. A
    statement with no silver row yet is left out (its build reads bronze)."""
    from src.lakehouse.fabric_sql import get_warehouse_connection

    wanted = _azure_values_by_statement(statement_ids)
    conn = get_warehouse_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT statement_id, {', '.join(LOCATION_COLUMNS)} FROM silver.statement")
        silver = {row[0]: dict(zip(LOCATION_COLUMNS, row[1:])) for row in cur.fetchall()}
    finally:
        conn.close()
    return {sid: values for sid, values in wanted.items() if sid in silver and silver[sid] != values}


def _merge_bronze(plan: dict) -> None:
    """One Delta MERGE for all the statements (each merge scans the whole table,
    so one is much cheaper than several), under the pipeline lock; retried when
    a concurrent write makes the commit fail."""
    import pandas as pd
    from deltalake import DeltaTable
    from src.lakehouse.bronze_raw import _storage_options, _table_uri
    from src.lakehouse.fabric_dbt_runner import fabric_pipeline_lock

    df = pd.DataFrame([{"statement_id": sid, **values} for sid, values in plan.items()])
    for column in ("statement_id", *LOCATION_COLUMNS):
        df[column] = df[column].astype("string")
    for attempt in range(1, MERGE_ATTEMPTS + 1):
        try:
            with fabric_pipeline_lock():
                (DeltaTable(_table_uri(), storage_options=_storage_options())
                 .merge(source=df, predicate="t.statement_id = s.statement_id", source_alias="s", target_alias="t")
                 .when_matched_update(updates={column: f"s.{column}" for column in LOCATION_COLUMNS})
                 .execute())
            return
        except Exception as exc:
            # A merge scans the whole table, so a row appended meanwhile (by the
            # app, which this process's lock cannot exclude) fails the commit.
            if attempt == MERGE_ATTEMPTS or "concurrent" not in str(exc).lower():
                raise
            logger.warning("bronze merge conflicted with a concurrent write (attempt %d of %d) -- retrying",
                           attempt, MERGE_ATTEMPTS)


def _update_silver_many(plan: dict) -> int:
    """UPDATE silver.statement per statement on one connection, committing in
    batches. Returns how many were updated."""
    from src.lakehouse.fabric_sql import get_warehouse_connection

    conn = get_warehouse_connection()
    done = 0
    try:
        cur = conn.cursor()
        for sid, values in plan.items():
            cur.execute(f"UPDATE silver.statement SET {', '.join(f'{c} = ?' for c in LOCATION_COLUMNS)} "
                        "WHERE statement_id = ?", [values[c] for c in LOCATION_COLUMNS] + [sid])
            done += 1
            if done % SILVER_COMMIT_EVERY == 0:
                conn.commit()
        conn.commit()
    finally:
        conn.close()
    return done


def sync_many(plan: dict, log=print) -> dict:
    """Copies a plan_sync() plan to Fabric: all of bronze first, then silver, so
    silver never holds a location bronze lacks. Raises on failure (it is for
    scripts, which show the error); re-running continues, because plan_sync()
    lists only what still differs."""
    if not plan:
        return {"bronze": 0, "silver": 0}
    _merge_bronze(plan)
    log(f"  bronze.raw_statement: {len(plan)} statements merged")
    silver = _update_silver_many(plan)
    log(f"  silver.statement: {silver} statements updated")
    return {"bronze": len(plan), "silver": silver}


def sync_in_background(statement_id: str) -> None:
    """sync_statement_location() on a thread, for a web request that must not
    wait for the Fabric lock."""
    threading.Thread(target=sync_statement_location, args=(statement_id,), daemon=True,
                     name=f"fabric-location-{statement_id}").start()
