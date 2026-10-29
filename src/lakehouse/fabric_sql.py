"""Shared connection helpers for querying the Fabric Lakehouse/Warehouse
directly over T-SQL (pyodbc + a pre-fetched AAD token), used by
fabric_bronze.py and the matching module. Same auth mechanism as
get_fabric_connection() in connection.py (out-of-band SQL_COPT_SS_ACCESS_TOKEN),
just targeting the new service-principal-based Fabric workspace instead of
the existing SQL-database-in-Fabric cut-over.
"""
import logging
import os
import struct
import threading
import time

logger = logging.getLogger(__name__)

SQL_COPT_SS_ACCESS_TOKEN = 1256

# Cached at module level so repeated calls reuse the same ClientSecretCredential
# instance instead of discarding it (and the AAD token it internally caches)
# after every single query. azure-identity's credential classes already cache
# and silently refresh their token on expiry (Fabric/AAD tokens are typically
# valid ~60-90 min) -- recreating the credential object per call was throwing
# that cache away every time, forcing a fresh AAD auth round-trip (~4-8s,
# measured) on every recon_query()/recon_sql() call. Confirmed as the
# dominant cost behind the /exceptions page's ~55s load with only 4 vendors
# (2026-09-02 investigation) -- not caching the pyodbc connection itself here,
# since get_lakehouse_connection()/get_warehouse_connection() are also called
# directly (not just via execute_warehouse_query/execute_warehouse_sql) by
# netsuite_vendor_resolver.py, fabric_matching.py, and fabric_dbt_runner.py,
# which hold and close their own connection -- sharing one pyodbc connection
# across those callers would risk both thread-safety and one caller's
# close() breaking another's in-flight query.
_credential = None


def _get_credential():
    global _credential
    if _credential is None:
        from azure.identity import ClientSecretCredential

        _credential = ClientSecretCredential(
            tenant_id=os.environ["FABRIC_TENANT_ID"],
            client_id=os.environ["FABRIC_CLIENT_ID"],
            client_secret=os.environ["FABRIC_CLIENT_SECRET"],
        )
    return _credential


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


# Reused read connections (2026-10-29). Every page's queries used to open a
# fresh Fabric connection per query (~0.3-1 s each, more after a quiet
# spell); now execute_lakehouse_query()/execute_warehouse_query() take an
# idle one from a small per-database pool and give it back after the query.
# A connection idle for over _POOL_IDLE_SECONDS (under Azure's ~4 min
# idle-drop of outbound connections) or older than _POOL_MAX_AGE_SECONDS is
# closed rather than reused, and a query that fails on a reused connection is
# retried once on a fresh one. Callers that hold their own connection
# (get_*_connection(): matching, dbt, the vendor resolver) are unchanged, and
# so is execute_warehouse_sql() (writes keep a connection of their own).
_POOL_IDLE_SECONDS = 180
_POOL_MAX_AGE_SECONDS = 1800
_POOL_MAX_IDLE = 4
_pools = {}  # database -> [(conn, opened_at, last_used), ...]
_pool_lock = threading.Lock()


def _close_quietly(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass


def _take(database: str):
    """(conn, opened_at, reused) -- an idle pooled connection still fit to
    use, else a new one."""
    now = time.monotonic()
    stale = []
    taken = None
    with _pool_lock:
        pool = _pools.setdefault(database, [])
        while pool:
            conn, opened_at, last_used = pool.pop()
            if now - last_used < _POOL_IDLE_SECONDS and now - opened_at < _POOL_MAX_AGE_SECONDS:
                taken = (conn, opened_at, True)
                break
            stale.append(conn)
    for conn in stale:
        _close_quietly(conn)
    return taken or (_connect(database), time.monotonic(), False)


def _give_back(database: str, conn, opened_at) -> None:
    with _pool_lock:
        pool = _pools.setdefault(database, [])
        if len(pool) < _POOL_MAX_IDLE:
            pool.append((conn, opened_at, time.monotonic()))
            return
    _close_quietly(conn)


def _pooled_query(database: str, sql, params) -> list:
    for attempt in (1, 2):
        conn, opened_at, reused = _take(database)
        try:
            cur = conn.cursor()
            cur.execute(sql, params or [])
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception:
            _close_quietly(conn)
            if not reused or attempt == 2:
                raise
            logger.warning("Fabric query failed on a reused connection -- retrying on a new one", exc_info=True)
            continue
        _give_back(database, conn, opened_at)
        return rows


def execute_lakehouse_query(sql, params=None) -> list:
    """Fabric-Lakehouse-backed equivalent of execute_warehouse_query() --
    same signature, same return shape (list of dicts), on a reused
    connection (see _pooled_query())."""
    return _pooled_query(os.environ["FABRIC_LAKEHOUSE_NAME"], sql, params)


def execute_warehouse_query(sql, params=None) -> list:
    """Fabric-Warehouse-backed equivalent of
    src.lakehouse.connection.execute_query() -- same signature, same
    return shape (list of dicts) -- so callers written against the local
    Azure SQL/SQLite backend can switch to this with a one-line import
    change. On a reused connection (see _pooled_query())."""
    return _pooled_query(os.environ["FABRIC_WAREHOUSE_NAME"], sql, params)


def execute_warehouse_sql(sql, params=None) -> None:
    """Fabric-Warehouse-backed equivalent of
    src.lakehouse.connection.execute_sql() -- same signature. Explicit
    commit (pyodbc connections aren't autocommit by default)."""
    conn = get_warehouse_connection()
    cur = conn.cursor()
    cur.execute(sql, params or [])
    conn.commit()


# SQL Server caps one statement at 2100 parameters -- stay under it.
_MAX_PARAMS_PER_INSERT = 2000


def insert_rows(cur, table: str, columns: list, rows: list) -> int:
    """Inserts rows (list of sequences, in `columns` order) into `table`
    with as few multi-row INSERT statements as the parameter cap allows,
    on the caller's cursor -- so they share the caller's transaction and
    commit. Never row-by-row: a single-row INSERT costs ~0.25-0.35s
    against this Warehouse (measured 2026-09-28), which is what made
    matching take 36-77s per statement.

    Plain INSERTs are also what lets concurrent jobs write the same table
    safely: Fabric Warehouse raises write-write conflicts for concurrent
    UPDATE/DELETE/MERGE on a table, not for appends.

    String parameters are bound as nvarchar(max): pyodbc otherwise sends
    any string over 4000 chars as legacy ntext, which Fabric's UTF-8
    collation rejects. `table` and `columns` are interpolated as SQL
    identifiers -- callers pass fixed names only, never user input."""
    if not rows:
        return 0

    import pyodbc

    rows_per_insert = max(1, _MAX_PARAMS_PER_INSERT // len(columns))
    column_list = ", ".join(columns)
    row_placeholder = "(" + ", ".join("?" for _ in columns) + ")"
    try:
        for start in range(0, len(rows), rows_per_insert):
            chunk = rows[start:start + rows_per_insert]
            params = [value for row in chunk for value in row]
            cur.setinputsizes([
                (pyodbc.SQL_WVARCHAR, 0, 0) if isinstance(p, str) else None
                for p in params
            ])
            cur.execute(
                f"INSERT INTO {table} ({column_list}) VALUES "
                + ", ".join(row_placeholder for _ in chunk),
                params,
            )
    finally:
        # setinputsizes() sticks to the cursor -- clear it so the caller's
        # next execute() on this same cursor binds normally.
        cur.setinputsizes(None)
    return len(rows)