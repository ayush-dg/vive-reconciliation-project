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

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "lakehouse", "reconciliation.db")

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


def execute_sql(sql, params=None):
    """Execute a single SQL statement and return the cursor."""
    conn = get_connection()
    try:
        if _using_azure_sql():
            sql = _translate_for_azure(sql)
        cursor = conn.execute(sql, params or [])
        conn.commit()
        return cursor
    finally:
        conn.close()


def execute_query(sql, params=None):
    """Execute a SELECT and return all rows as list of dicts."""
    conn = get_connection()
    try:
        if _using_azure_sql():
            sql = _translate_for_azure(sql)
        cursor = conn.execute(sql, params or [])
        rows = cursor.fetchall()
        if _using_azure_sql():
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
        return [dict(row) for row in rows]
    finally:
        conn.close()
