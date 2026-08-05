## G10 — SQLite migration runner
ID: M-034
Layer: infra
Source file: src/lakehouse/migrations.py

**Module** — SQLite migration runner
**ID** — M-034
**Layer** — infra
**Primary Responsibility** — Applies numbered SQL migration files from `migrations/` against the lakehouse database, tracking what's applied in `schema_version`.

**Inputs** — `apply_pending_migrations(conn)` — a live DB connection.

**Outputs** — Applies pending `CREATE TABLE`/`ALTER TABLE` DDL; writes `schema_version` rows. Returns `list[(version_str, filename)]` for migrations applied this call.

**Public Interface**
- `apply_pending_migrations(conn) -> list[tuple[str, str]]`
- `class MigrationError(Exception)`
- `_ensure_schema_version_table(conn)`, `_discover_migrations()`, `_get_applied_versions(conn)`, `_strip_line_comments(sql_text)`, `_split_statements(sql_text)`, `_apply_migration(conn, version_str, filename, full_path)` (all private)

**Error Behaviour**
- **Each migration file is applied in exactly one transaction** (`BEGIN`/`COMMIT`, with `ROLLBACK` + `MigrationError` on any statement failure) that also records the `schema_version` row in the same transaction — confirmed by source: either the whole migration (DDL + bookkeeping) commits, or neither does. Verified in this session: migrations 004-006 applied cleanly, `schema_version` now correctly shows all 6.
- **`_discover_migrations()` raises `MigrationError` on a duplicate numeric prefix** — two files claiming the same migration number is a fail-loud, not a silent pick of one arbitrarily.
- **`apply_pending_migrations()` stops at the first failure** — does not attempt later migrations, and does not record the failed one as applied (consistent with the per-file transaction guarantee above).

**Known Fragility** — `_split_statements()`/`_strip_line_comments()` are explicitly documented (own comments, confirmed by reading the actual regex/split logic) as *not* a general SQL parser — safe only because this project's migration files are "plain CREATE TABLE / ALTER TABLE DDL, no string literals containing `--` or embedded semicolons, no trigger bodies." A future migration file that violates any of those assumptions (e.g. a DEFAULT value containing `--` in a string literal) would silently mis-split, likely producing a confusing SQL syntax error rather than an obviously-wrong one.

**Change Impact** — Any new migration file just needs to follow the `NNN_description.sql` naming convention (zero-padded to 3 digits) — automatically discovered and applied in order. No code change needed for new migrations.

**Callers** — M-019 (`notebooks/00_setup_lakehouse_schema.py`)
**Calls** — none (operates directly on the connection passed in)
**Integration Points Used** — IP-008 (Lakehouse database — SQLite side only; the Azure SQL side has its own separate creator, M-035)
