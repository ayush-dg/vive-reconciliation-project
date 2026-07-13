"""
migrations.py

Applies numbered SQL migration files from migrations/ against the lakehouse
database, tracking what's been applied in schema_version.

See RULES.md RULE-12 — schema changes go through a new numbered migration
file here, never a manual edit to an existing migration or a direct edit
to the database.

Migration files: migrations/NNN_description.sql, zero-padded to 3 digits.
Discovered by parsing the leading numeric prefix (not a pure string sort),
applied in ascending order. Each file is applied in one transaction that
also records the schema_version row — either the whole migration (schema
change + the record that it happened) commits, or neither does, so
schema_version can never drift from actual database state.
"""

import os
import re
from datetime import datetime, timezone

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "migrations")

_FILENAME_RE = re.compile(r"^(\d+)_.*\.sql$")


class MigrationError(Exception):
    """Raised when a migration fails to apply. Wraps the original error
    with which migration file failed, so it's never swallowed silently."""
    pass


def _ensure_schema_version_table(conn):
    """Bootstrap step — must succeed before anything else can run, since
    every other operation here needs to read/write this table. Safe to run
    every time: CREATE TABLE IF NOT EXISTS is a no-op once it exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
    """)
    conn.commit()


def _discover_migrations():
    """Returns [(version_str, filename, full_path), ...] sorted by the
    numeric prefix, not a plain string sort (so width changes can't
    misorder them). Raises MigrationError if two files share a prefix."""
    if not os.path.isdir(MIGRATIONS_DIR):
        return []

    found = {}
    for filename in os.listdir(MIGRATIONS_DIR):
        match = _FILENAME_RE.match(filename)
        if not match:
            continue
        version_str = match.group(1)
        version_num = int(version_str)
        if version_num in found:
            raise MigrationError(
                f"Duplicate migration number {version_num}: "
                f"'{found[version_num][1]}' and '{filename}' both claim it"
            )
        found[version_num] = (version_str, filename, os.path.join(MIGRATIONS_DIR, filename))

    return [found[n] for n in sorted(found.keys())]


def _get_applied_versions(conn):
    rows = conn.execute("SELECT version FROM schema_version").fetchall()
    return {row[0] for row in rows}


def _strip_line_comments(sql_text: str) -> str:
    """Remove '-- ...' line comments before statement splitting, so a
    semicolon inside a comment can't be mistaken for a statement boundary.
    Not string-literal-aware — safe here because this project's migration
    files don't use '--' inside string literals, only in real comments."""
    lines = []
    for line in sql_text.split("\n"):
        idx = line.find("--")
        lines.append(line[:idx] if idx != -1 else line)
    return "\n".join(lines)


def _split_statements(sql_text: str):
    """Split a migration file into individual statements on ';'.

    Safe for this project's migration files (plain CREATE TABLE / ALTER
    TABLE DDL, no string literals containing '--' or embedded semicolons,
    no trigger bodies) — not a general-purpose SQL parser.
    """
    sql_text = _strip_line_comments(sql_text)
    statements = []
    for raw in sql_text.split(";"):
        stmt = raw.strip()
        if stmt:
            statements.append(stmt)
    return statements


def _apply_migration(conn, version_str, filename, full_path):
    with open(full_path, "r", encoding="utf-8") as f:
        sql_text = f.read()

    statements = _split_statements(sql_text)
    now = datetime.now(timezone.utc).isoformat()

    conn.execute("BEGIN")
    try:
        for stmt in statements:
            conn.execute(stmt)
        conn.execute(
            "INSERT INTO schema_version (version, filename, applied_at) VALUES (?, ?, ?)",
            [version_str, filename, now],
        )
        conn.execute("COMMIT")
    except Exception as e:
        conn.execute("ROLLBACK")
        raise MigrationError(f"Migration {filename} failed and was rolled back: {e}") from e


def apply_pending_migrations(conn):
    """
    Applies every migration in migrations/ not yet recorded in
    schema_version, in ascending numeric order, one transaction per file.

    Returns a list of (version_str, filename) tuples for migrations that
    were actually applied during this call (empty if everything was
    already up to date).

    Raises MigrationError on the first failure — does not attempt later
    migrations, and does not record the failed one as applied.
    """
    _ensure_schema_version_table(conn)
    applied_versions = _get_applied_versions(conn)
    migrations = _discover_migrations()

    newly_applied = []
    for version_str, filename, full_path in migrations:
        if version_str in applied_versions:
            continue
        _apply_migration(conn, version_str, filename, full_path)
        newly_applied.append((version_str, filename))

    return newly_applied
