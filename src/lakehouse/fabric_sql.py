"""Shared connection helpers for querying the Fabric Lakehouse/Warehouse
directly over T-SQL (pyodbc + a pre-fetched AAD token), used by
fabric_bronze.py and the matching module. Same auth mechanism as
get_fabric_connection() in connection.py (out-of-band SQL_COPT_SS_ACCESS_TOKEN),
just targeting the new service-principal-based Fabric workspace instead of
the existing SQL-database-in-Fabric cut-over.
"""
import os
import struct

SQL_COPT_SS_ACCESS_TOKEN = 1256


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
    low-frequency admin/UI reads, not a hot path."""
    conn = get_warehouse_connection()
    cur = conn.cursor()
    cur.execute(sql, params or [])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def execute_warehouse_sql(sql, params=None) -> None:
    """Fabric-Warehouse-backed equivalent of
    src.lakehouse.connection.execute_sql() -- same signature. Explicit
    commit (pyodbc connections aren't autocommit by default)."""
    conn = get_warehouse_connection()
    cur = conn.cursor()
    cur.execute(sql, params or [])
    conn.commit()
