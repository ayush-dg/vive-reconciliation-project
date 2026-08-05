## G05 — lakehouse schema setup
ID: M-019
Layer: infra
Source file: notebooks/00_setup_lakehouse_schema.py

**Module** — lakehouse schema setup
**ID** — M-019
**Layer** — infra
**Primary Responsibility** — Applies every pending migration in `migrations/` to bring the lakehouse database up to date; safe to re-run at any time.

**Inputs** — None (no CLI args; targets whichever backend `src/lakehouse/connection.py` resolves — SQLite or Azure SQL, based on `AZURE_SQL_SERVER`).

**Outputs** — Prints which migrations were newly applied (or "schema already up to date"), then prints the full current table list and full applied-migrations history, regardless of what this specific run touched — confirmed by direct read: the verification step re-queries `sqlite_master`/`schema_version` fresh rather than tracking only this run's deltas.

**Public Interface**
- `setup_schema() -> list[tuple[str, str]]` — importable; returns `(version_str, filename)` tuples for newly-applied migrations.

**Error Behaviour** — No try/except of its own; delegates entirely to `apply_pending_migrations()` (M-034), which raises `MigrationError` on the first failing migration (transaction rolled back, nothing recorded). This script does not catch that — a failure here halts the script with a traceback, correctly STARTUP-FATAL for its own run (does not corrupt state, per M-034's transaction guarantee).

**Known Fragility** — None specific — this is a thin, correctly-scoped wrapper. Its own comment explicitly notes the verification/reporting step deliberately re-derives state fresh "not just what this run happened to touch," which was confirmed accurate by direct read (this session used it to verify migrations 004-006 applied cleanly).

**Change Impact** — Any new migration file added to `migrations/` is automatically picked up on the next run — no code change needed here.

**Callers** — none (invoked directly, `python notebooks/00_setup_lakehouse_schema.py`; engineer-run in this session on 2026-07-23 to apply migrations 004-006 locally)
**Calls** — M-033 (`get_connection`), M-034 (`apply_pending_migrations`)
**Integration Points Used** — IP-008 (Lakehouse database)
