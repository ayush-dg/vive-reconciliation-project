## C01 — Lakehouse Schema Setup Entry Point
ID: M-016
Layer: pipeline
Source file: `notebooks/00_setup_lakehouse_schema.py`

**Module** — Lakehouse Schema Setup Entry Point
**ID** — M-016
**Layer** — pipeline
**Primary Responsibility** — CLI entry point that applies every pending SQLite migration and prints the resulting schema state.

**Inputs** — None (no arguments).

**Outputs** — Applied migrations recorded in `schema_version`; stdout listing of tables and applied migrations.

**Public Interface** — `setup_schema()` — callable programmatically, returns the list of newly-applied `(version, filename)` tuples.

**Error Behaviour** — `apply_pending_migrations()` (M-038) raises `MigrationError` on any failure — not caught here, propagates to the CLI as an uncaught exception/traceback.

**Known Fragility** — None beyond what M-038 already carries; this is a thin wrapper.

**Change Impact** — Isolated; only ever run manually or as part of initial setup, not called by any other runtime module.

**Callers** — none (developer-invoked CLI entry point)
**Calls** — M-037 (`get_connection`), M-038 (`apply_pending_migrations`)
**Integration Points Used** — IP-008 (Azure SQL/SQLite, via M-037)
