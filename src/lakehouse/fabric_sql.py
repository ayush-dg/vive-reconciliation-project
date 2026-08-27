"""Shared connection helpers for querying the Fabric Lakehouse/Warehouse
directly over T-SQL (pyodbc + a pre-fetched AAD token), used by
fabric_bronze.py and the matching module. Same auth mechanism as
get_fabric_connection() in connection.py (out-of-band SQL_COPT_SS_ACCESS_TOKEN),
just targeting the new service-principal-based Fabric workspace instead of
the existing SQL-database-in-Fabric cut-over.

execute_warehouse_query()/execute_warehouse_sql() are the two functions
web/queries.py calls (as recon_query/recon_sql) for every silver.recon_*
read and write behind the Exceptions page -- including sidebar_context(),
which runs on every single authenticated page. Without the
_fabric_configured() guard below, anyone without the Fabric service-
principal env vars set (FABRIC_TENANT_ID/CLIENT_ID/CLIENT_SECRET/
SQL_ENDPOINT/WAREHOUSE_NAME -- .env is gitignored, so a fresh checkout or
a teammate's machine never has these unless separately shared) got a raw
KeyError out of os.environ[...] on literally every page load, not just
the Exceptions page -- a real incident, not a hypothetical. Matches the
same _fabric_configured() pattern already used in fabric_dbt_runner.py/
fabric_bronze.py for the write side of this pipeline: additive, never
blocks the rest of the app.
"""
import logging
import os
import struct

logger = logging.getLogger(__name__)

SQL_COPT_SS_ACCESS_TOKEN = 1256


def _fabric_configured() -> bool:
    return bool(
        os.getenv("FABRIC_TENANT_ID")
        and os.getenv("FABRIC_CLIENT_ID")
        and os.getenv("FABRIC_CLIENT_SECRET")
        and os.getenv("FABRIC_SQL_ENDPOINT")
        and os.getenv("FABRIC_WAREHOUSE_NAME")
    )


def _get_credential():
    from azure.identity import ClientSecretCredential

    return ClientSecretCredential(
        tenant_id=os.environ["FABRIC_TENANT_ID"],
        client_id=os.environ["FABRIC_CLIENT_ID"],
        client_secret=os.environ["FABRIC_CLIENT_SECRET"],
    )


def _connect(database: str):
    import pyodbc

    token = _get_credential().get_token("https://database.windows.net/.default")
    token_bytes = token.token.encode("utf-16-le")
    token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)
    conn_str = (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server={os.environ['FABRIC_SQL_ENDPOINT']},1433;"
        f"Database={database};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct})


def get_lakehouse_connection():
    """Connects directly to the Lakehouse's own SQL analytics endpoint
    (bronze.* tables -- statement Bronze, and the existing NetSuite/CCC ONE
    ingestion's tables)."""
    return _connect(os.environ["FABRIC_LAKEHOUSE_NAME"])


def get_warehouse_connection():
    """Connects to the Warehouse (silver.* tables), which can also
    cross-query the Lakehouse via three-part names (same workspace)."""
    return _connect(os.environ["FABRIC_WAREHOUSE_NAME"])


def execute_warehouse_query(sql, params=None) -> list:
    """Fabric-Warehouse-backed equivalent of
    src.lakehouse.connection.execute_query() -- same signature, same
    return shape (list of dicts) -- so callers written against the local
    Azure SQL/SQLite backend can switch to this with a one-line import
    change. A fresh connection per call (no pooling) -- these are
    low-frequency admin/UI reads, not a hot path.

    Returns [] (never raises) when Fabric isn't configured -- see this
    module's docstring. Every caller in web/queries.py already treats an
    empty result as "no data yet" (an empty Exceptions page, a 0 sidebar
    count), which is the correct degraded state here, not a crash."""
    if not _fabric_configured():
        logger.warning("Fabric not configured -- returning no rows for a silver.* query")
        return []
    conn = get_warehouse_connection()
    cur = conn.cursor()
    cur.execute(sql, params or [])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def execute_warehouse_sql(sql, params=None) -> None:
    """Fabric-Warehouse-backed equivalent of
    src.lakehouse.connection.execute_sql() -- same signature. Explicit
    commit (pyodbc connections aren't autocommit by default).

    No-ops (never raises) when Fabric isn't configured -- see this
    module's docstring. A write silently doing nothing is a real
    limitation (e.g. resolving an exception won't actually persist), but
    it's strictly better than crashing the request; there's no exception
    data to act on in that state anyway since execute_warehouse_query()
    is returning [] for the same reason."""
    if not _fabric_configured():
        logger.warning("Fabric not configured -- skipping a silver.* write")
        return
    conn = get_warehouse_connection()
    cur = conn.cursor()
    cur.execute(sql, params or [])
    conn.commit()
