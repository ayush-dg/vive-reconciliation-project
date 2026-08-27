## G03 — Azure SQL Schema Creator
ID: M-039
Layer: infra
Source file: `src/lakehouse/azure_sql_migrations.py`

**Module** — Azure SQL Schema Creator
**ID** — M-039
**Layer** — infra
**Primary Responsibility** — One-shot, idempotently re-runnable T-SQL DDL creator mirroring the SQLite migration files' end-state schema for Azure SQL — not a tracked/numbered migration runner; the SQLite files remain the source of truth for schema *history*.

**Inputs** — A live Azure SQL connection (via M-037's `get_connection()`); its own hardcoded `TABLES`/`INDEXES`/`COLUMNS`/`COMPUTED_COLUMNS` dicts.

**Outputs** — Tables/indexes/columns created in Azure SQL, guarded by `IF NOT EXISTS`-equivalent checks against `sys.tables`/`sys.indexes`/`sys.columns`.

**Public Interface** — `run_migrations() -> (created_tables, created_indexes, created_columns)`, `list_tables() -> list`. Also runnable as a script (`if __name__ == "__main__"`) which exits early with a message if `AZURE_SQL_SERVER` isn't set.

**Error Behaviour** — No explicit error handling — a DDL failure (e.g. a syntax error in one of the hardcoded `CREATE TABLE` strings) propagates as an uncaught `pyodbc` exception; the surrounding `try/finally` only guarantees the connection is closed, not that partial DDL is rolled back.

**Known Fragility**
- **This file must be kept manually in sync with the 9 SQLite migration files** — confirmed this session (Session F01) that they currently agree exactly, including the one deliberate platform difference (`gold_exceptions.days_open` as a true computed column here, absent from SQLite by necessity) — but nothing enforces this agreement structurally. A SQLite migration added without a corresponding update here would silently leave Azure SQL's schema behind, with no automated check to catch the drift (confirmed as a real, tracked risk in the archived `RISK_REGISTER.md` R-006).
- `COLUMNS` (plain ALTER) and `COMPUTED_COLUMNS` (generated-column ALTER) are deliberately kept as separate dicts specifically so a computed column's different application semantics (never directly INSERT/UPDATE-targeted) stays visually distinct from a plain column — a maintainer merging them without preserving that distinction risks someone writing application code that tries to write directly to `days_open`.
- `run_migrations()`'s per-column ALTER checks run unconditionally on every call, even against a table that was just newly created in the same call (whose columns already include everything in `COLUMNS`) — harmless (the `sys.columns` check correctly finds them already present) but a redundant pass every single invocation.

**Change Impact** — The sole path by which Azure SQL's schema comes to match the SQLite migrations' end state — any divergence here directly risks a production (Azure SQL) deployment running against a schema different from what the numbered SQLite migrations describe.

**Callers** — none identified this session (appears to be run manually/via deployment tooling, not called from any other module in this codebase)
**Calls** — M-037 (`get_connection`)
**Integration Points Used** — IP-008 (Azure SQL, via M-037)
