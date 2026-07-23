## G11 — Azure SQL schema creator
ID: M-035
Layer: infra
Source file: src/lakehouse/azure_sql_migrations.py

**Module** — Azure SQL schema creator
**ID** — M-035
**Layer** — infra
**Primary Responsibility** — Creates the full lakehouse schema directly in Azure SQL using T-SQL DDL — the Azure-SQL equivalent of the SQLite migration files, but a one-shot re-runnable creator, not a numbered migration runner.

**Inputs** — None as a script (`python src/lakehouse/azure_sql_migrations.py`); reads `AZURE_SQL_SERVER` env var to confirm it should run at all.

**Outputs** — Creates any of 14 tables (`TABLES` dict), 2 indexes (`INDEXES` dict), and applies column additions (`COLUMNS` dict, currently only `jobs.claim_token`) that don't already exist in the connected Azure SQL database. Prints what was created.

**Public Interface**
- `run_migrations() -> tuple[list, list, list]` — `(created_tables, created_indexes, created_columns)`, importable.
- `list_tables() -> list[str]`
- `TABLES`, `INDEXES`, `COLUMNS` (module-level dicts — the actual schema source of truth for the Azure SQL side).

**Error Behaviour** — `if __name__ == "__main__"` guard exits with `sys.exit(1)` and a clear message if `AZURE_SQL_SERVER` is unset — "this script only targets Azure SQL," a deliberate fail-fast rather than silently no-op-ing against SQLite. No try/except around the actual `CREATE TABLE`/`ALTER TABLE` calls — a genuine schema conflict (e.g. a table existing with an incompatible shape) would raise a pyodbc error uncaught.

**Known Fragility**
- **This file is a second, independently-maintained source of schema truth**, parallel to the SQLite migration files under `migrations/` — its own docstring explicitly says the SQLite files "remain the source of truth for schema history," meaning this file's `TABLES`/`INDEXES`/`COLUMNS` dicts must be kept manually in sync with every new SQLite migration. Confirmed by this session's work: migrations 004-006 (`users`, `jobs`, `claim_token`) already have corresponding entries here (`"users"`, `"jobs"` in `TABLES`, `"claim_token"` in `COLUMNS`) — currently in sync, but nothing enforces that going forward. A new SQLite migration added without a corresponding update here would silently never reach Azure SQL via this script (though `notebooks/00_setup_lakehouse_schema.py` + `src/lakehouse/migrations.py` don't run against Azure SQL at all — this script is the *only* path that provisions Azure SQL schema, so a missed update here is a real, silent provisioning gap for that environment).
- `COLUMNS`'s own comment explains precisely why it's a separate mechanism from `TABLES`: a table's `CREATE TABLE IF NOT EXISTS` becomes a permanent no-op once the table exists, so a column added to an existing table's *definition* in `TABLES` would never actually reach a live database that already has that table — it must be re-declared in `COLUMNS` and applied unconditionally every run. This is a real, non-obvious footgun for future schema changes, correctly worked around here but easy to forget.

**Change Impact** — Every new SQLite migration (`migrations/NNN_*.sql`) that adds a table or column requires a manual, parallel update to this file's `TABLES`/`COLUMNS` dicts to reach Azure SQL — no automated sync exists between the two schema-definition mechanisms.

**Callers** — none (invoked directly as a script; not imported/called by any other module in the traced call graph)
**Calls** — M-033 (`get_connection`)
**Integration Points Used** — IP-008 (Lakehouse database — Azure SQL side)
