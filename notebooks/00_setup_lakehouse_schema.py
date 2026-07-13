"""
00_setup_lakehouse_schema.py

Applies every pending migration in migrations/ to bring the lakehouse
database up to date. Safe to re-run at any time — already-applied
migrations are skipped (see src/lakehouse/migrations.py).

Locally this targets SQLite via src/lakehouse/connection.py. In production
(Microsoft Fabric), the same DDL structure maps onto Delta tables — only
connection.py changes.

See RULES.md RULE-12 — schema changes are new migration files under
migrations/, never a direct edit to this script or the database.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse.connection import get_connection
from src.lakehouse.migrations import apply_pending_migrations


def setup_schema():
    conn = get_connection()
    try:
        newly_applied = apply_pending_migrations(conn)
    finally:
        conn.close()
    return newly_applied


if __name__ == "__main__":
    newly_applied = setup_schema()

    if newly_applied:
        for version_str, filename in newly_applied:
            print(f"Applied migration {version_str}: {filename}")
    else:
        print("No pending migrations — schema already up to date")

    # Verification — reflects actual current database state, not just
    # what this run happened to touch, matching every table that's ever
    # existed regardless of whether it was created this run or before.
    conn = get_connection()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    applied = conn.execute(
        "SELECT version, filename, applied_at FROM schema_version ORDER BY version"
    ).fetchall()
    conn.close()

    print()
    for t in tables:
        if t["name"] in ("schema_version", "sqlite_sequence"):
            continue
        print(f"Created (or verified) table: {t['name']}")

    print("\nTables in reconciliation.db:")
    for t in tables:
        print(f"  - {t['name']}")

    print("\nApplied migrations:")
    for row in applied:
        print(f"  - {row['version']} ({row['filename']}) at {row['applied_at']}")

    print("\nPhase 1 complete — schema up to date")
