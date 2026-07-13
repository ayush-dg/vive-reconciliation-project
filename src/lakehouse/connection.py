"""
connection.py

The only file that knows the storage backend is SQLite locally.
Every other module gets a connection from here.
In production (Microsoft Fabric), this file is the only thing that changes —
swap SQLite for Fabric's Lakehouse SQL endpoint.

See RULES.md RULE-06 — mock ERP data is a deliberate placeholder for a real
NetSuite integration, not yet built. This isolation (plus the record_source
field in silver_reconciliation_standard) is what keeps that future swap narrow.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "lakehouse", "reconciliation.db")


def get_connection():
    """Returns a SQLite connection. Creates the DB file if it doesn't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # so rows behave like dicts
    conn.execute("PRAGMA journal_mode=WAL")  # better concurrent read performance
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def execute_sql(sql, params=None):
    """Execute a single SQL statement and return the cursor."""
    conn = get_connection()
    try:
        cursor = conn.execute(sql, params or [])
        conn.commit()
        return cursor
    finally:
        conn.close()


def execute_query(sql, params=None):
    """Execute a SELECT and return all rows as list of dicts."""
    conn = get_connection()
    try:
        cursor = conn.execute(sql, params or [])
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
