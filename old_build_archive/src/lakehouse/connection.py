"""
connection.py

The only file that knows the storage backend. Locally (and in tests), it's
SQLite. In production, it's Azure SQL — selected automatically by whether
AZURE_SQL_SERVER is set in the environment (see .env). Every other module
gets a connection from here and writes backend-agnostic SQL against it;
this file is where the SQLite-vs-Azure-SQL dialect differences (INSERT OR
REPLACE vs MERGE, trailing LIMIT vs SELECT TOP) are absorbed, via
execute_sql()/execute_query(), so callers never need their own branching.

See RULES.md RULE-06 — mock ERP data is a deliberate placeholder for a real
NetSuite integration, not yet built. This isolation (plus the record_source
field in silver_reconciliation_standard) is what keeps that future swap narrow.

See RULES.md RULE-13 — Phase 3 switch to Azure SQL as the production backend.
"""

import sqlite3
import os
import re
import time

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "lakehouse", "reconciliation.db")

# Azure SQL serverless (free tier) auto-pauses when idle, and a long
# pipeline run's per-row connection pattern (write_to_bronze(),
# normalize_to_silver() in notebooks/01_document_intake.py) can outlast
# that pause window — the connection drops mid-run with SQLSTATE 08S01
# ("Communication link failure") or 08001 ("TCP Provider: Timeout").
# execute_sql()/execute_query() retry those specific errors with a fresh
# connection (never reusing the dropped one) before giving up.
CONNECTION_DROP_SQLSTATES = {"08S01", "08001"}
MAX_CONNECTION_RETRIES = 3
CONNECTION_RETRY_WAIT_SECONDS = 5

# Table -> unique key columns, used to translate "INSERT OR REPLACE INTO
# table (...)" (SQLite upsert syntax) into a T-SQL MERGE statement when
# running against Azure SQL. Add an entry here whenever a new INSERT OR
# REPLACE call site targets a table not already listed.
AZURE_UPSERT_KEYS = {
    "silver_reconciliation_standard": ["record_id"],
    "extraction_cache": ["document_hash", "statement_id"],
}

_INSERT_OR_REPLACE_RE = re.compile(
    r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\((.*?)\)\s*VALUES\s*\((.*?)\)\s*$",
    re.IGNORECASE | re.DOTALL,
)

_TRAILING_LIMIT_RE = re.compile(
    r"^\s*SELECT\s+(.*?)\s+LIMIT\s+(\d+)\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _using_azure_sql():
    return bool(os.getenv("AZURE_SQL_SERVER"))


def _using_fabric_warehouse():
    return bool(os.getenv("FABRIC_WORKSPACE_ID"))


def _using_fabric_sqldb():
    return bool(os.getenv("FABRIC_SQLDB_ENDPOINT"))


SQL_COPT_SS_ACCESS_TOKEN = 1256


# This uses an Azure CLI-issued token (AzureCliCredential + SQL_COPT_SS_ACCESS_TOKEN)
# instead of the ODBC driver's Authentication=ActiveDirectoryInteractive keyword.
# Interactive auth was tried first and fails on this machine with FA004/0x534 —
# the Windows WAM broker can't complete the sign-in. The CLI-token approach
# sidesteps the driver's own auth flow entirely and was confirmed working; it
# requires `az login` to have been run once already in this environment — it
# reuses that session rather than prompting for one. Do not switch this to
# Authentication=ActiveDirectoryInteractive — same WAM-broker failure mode.
#
# Repointed 2026-08-06 from Fabric Warehouse to a real "SQL database in
# Fabric" item (FABRIC_SQLDB_ENDPOINT/FABRIC_SQLDB_NAME) — same auth
# mechanism, different target. This is what actually resolves R-012/IC-19
# for these three tables: SQL database in Fabric supports IDENTITY columns
# (schema created by scripts/create_fabric_sqldb_schema.py — deliberately
# not a migrations/ file, see that script's docstring for why), Fabric
# Warehouse did not.
def get_fabric_connection():
    """Returns a connection for the Fabric-cut-over tables: extraction_cache,
    document_intake_log, validation_document_review_queue — see
    notebooks/01_document_intake.py's check_cache()/update_cache()/
    write_to_review_queue()/write_intake_log().

    Falls back to the SAME local SQLite backend (same DB_PATH) whenever
    Fabric itself isn't configured (FABRIC_SQLDB_ENDPOINT unset) — this is
    intentionally independent of _using_azure_sql(): plain Azure SQL and
    the Fabric SQL database item are two separate cut-overs (see the
    module docstring), and a deployment can have one configured without
    the other. Originally this checked _using_azure_sql() instead, on the
    assumption real Azure SQL and real Fabric would always be configured
    together — that assumption broke the first time someone ran against a
    real Azure SQL Database without a Fabric SQL database item also set
    up, sending get_fabric_connection() to a real Fabric endpoint that was
    never provided. AZURE_SQL_SERVER="" is still this codebase's
    established test-isolation convention for get_connection() — every
    test that already relies on it to get a clean local run (e.g.
    tests/test_level2_matching_integration.py) is unaffected, since a test
    environment with AZURE_SQL_SERVER unset also has FABRIC_SQLDB_ENDPOINT
    unset. Real Fabric (Azure CLI token auth) is only used when Fabric
    itself is genuinely configured."""
    if not _using_fabric_sqldb():
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    import struct

    import pyodbc
    from azure.identity import AzureCliCredential

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


def get_connection():
    """Returns a connection to the configured backend. Azure SQL (via
    pyodbc) if AZURE_SQL_SERVER is set in the environment, otherwise a
    local SQLite connection — creating the DB file if it doesn't exist."""
    if _using_azure_sql():
        import pyodbc

        server = os.getenv("AZURE_SQL_SERVER")
        database = os.getenv("AZURE_SQL_DATABASE")
        username = os.getenv("AZURE_SQL_USERNAME")
        password = os.getenv("AZURE_SQL_PASSWORD")
        conn_str = (
            "Driver={ODBC Driver 18 for SQL Server};"
            f"Server=tcp:{server},1433;"
            f"Database={database};"
            f"Uid={username};"
            f"Pwd={password};"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
            "Connection Timeout=30;"
        )
        return pyodbc.connect(conn_str)

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # so rows behave like dicts
    conn.execute("PRAGMA journal_mode=WAL")  # better concurrent read performance
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _translate_for_azure(sql):
    """Rewrites SQLite-only syntax into T-SQL equivalents. Only touches
    the two patterns this codebase actually uses (see module docstring) —
    not a general-purpose SQL dialect translator."""
    match = _INSERT_OR_REPLACE_RE.match(sql)
    if match:
        table, columns_raw, values_raw = match.groups()
        columns = [c.strip() for c in columns_raw.split(",")]
        if table not in AZURE_UPSERT_KEYS:
            raise NotImplementedError(
                f"No AZURE_UPSERT_KEYS entry for table '{table}' — add one in connection.py"
            )
        key_columns = AZURE_UPSERT_KEYS[table]
        src_cols = [f"? AS {c}" for c in columns]
        on_clause = " AND ".join(f"target.{k} = source.{k}" for k in key_columns)
        update_cols = [c for c in columns if c not in key_columns]
        update_clause = ", ".join(f"{c} = source.{c}" for c in update_cols)
        insert_cols = ", ".join(columns)
        insert_vals = ", ".join(f"source.{c}" for c in columns)
        return (
            f"MERGE INTO {table} AS target "
            f"USING (SELECT {', '.join(src_cols)}) AS source "
            f"ON {on_clause} "
            f"WHEN MATCHED THEN UPDATE SET {update_clause} "
            f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals});"
        )

    match = _TRAILING_LIMIT_RE.match(sql)
    if match:
        body, limit_n = match.groups()
        return f"SELECT TOP {limit_n} {body}"

    return sql


def _is_dropped_connection_error(exc) -> bool:
    """True if exc is a pyodbc error with SQLSTATE 08S01/08001 — a dropped
    or timed-out Azure SQL connection, worth retrying with a fresh
    connection. False for anything else (a genuine query/schema error, or
    any SQLite error), which should propagate immediately."""
    try:
        import pyodbc
    except ImportError:
        return False
    if not isinstance(exc, pyodbc.Error):
        return False
    sqlstate = exc.args[0] if exc.args else None
    return sqlstate in CONNECTION_DROP_SQLSTATES


def _run_with_retry(fn):
    """
    Calls fn(conn) with a fresh connection. If it raises a dropped-
    connection error (see _is_dropped_connection_error), retries up to
    MAX_CONNECTION_RETRIES times, each time discarding the dropped
    connection and opening a brand new one — never reusing it — after
    waiting CONNECTION_RETRY_WAIT_SECONDS. Any other error, or a dropped-
    connection error once retries are exhausted, re-raises the original
    exception unchanged.
    """
    for attempt in range(1, MAX_CONNECTION_RETRIES + 2):
        conn = get_connection()
        try:
            return fn(conn)
        except Exception as e:
            if _is_dropped_connection_error(e) and attempt <= MAX_CONNECTION_RETRIES:
                print(f"  Azure SQL connection dropped — retrying (attempt {attempt}/{MAX_CONNECTION_RETRIES})...")
                time.sleep(CONNECTION_RETRY_WAIT_SECONDS)
                continue
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass


def execute_sql(sql, params=None):
    """Execute a single SQL statement and return the cursor. Retries on a
    dropped Azure SQL connection — see _run_with_retry."""
    def _run(conn):
        stmt = _translate_for_azure(sql) if _using_azure_sql() else sql
        cursor = conn.execute(stmt, params or [])
        conn.commit()
        return cursor
    return _run_with_retry(_run)


def execute_query(sql, params=None):
    """Execute a SELECT and return all rows as list of dicts. Retries on a
    dropped Azure SQL connection — see _run_with_retry."""
    def _run(conn):
        stmt = _translate_for_azure(sql) if _using_azure_sql() else sql
        cursor = conn.execute(stmt, params or [])
        rows = cursor.fetchall()
        if _using_azure_sql():
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
        return [dict(row) for row in rows]
    return _run_with_retry(_run)


def execute_sql_fabric(sql, params=None):
    """Execute a single SQL statement against get_fabric_connection() and
    return the cursor — real SQL database in Fabric in production
    (repointed 2026-08-06, was Fabric Warehouse), the same
    local SQLite DB_PATH as execute_sql() in local/test mode (see
    get_fabric_connection()). No dialect translation and no drop-retry:
    callers must write SQL that's valid on both SQLite and T-SQL (no
    LIMIT/TOP, no INSERT OR REPLACE — see check_cache()/update_cache() in
    notebooks/01_document_intake.py for the pattern). Additive only;
    execute_sql() is untouched and still targets Azure SQL directly."""
    conn = get_fabric_connection()
    try:
        cursor = conn.execute(sql, params or [])
        conn.commit()
        return cursor
    finally:
        conn.close()


def execute_query_fabric(sql, params=None):
    """Execute a SELECT against get_fabric_connection() and return all
    rows as a list of dicts — real SQL database in Fabric in production
    (repointed 2026-08-06, was Fabric Warehouse), the
    same local SQLite DB_PATH as execute_query() in local/test mode (see
    get_fabric_connection()). dict(zip(columns, row)) works unchanged
    against both a pyodbc row and a sqlite3.Row, so no backend branching
    is needed here the way execute_query() needs for Azure SQL. Additive
    only; execute_query() is untouched and still targets Azure SQL
    directly."""
    conn = get_fabric_connection()
    try:
        cursor = conn.execute(sql, params or [])
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()
