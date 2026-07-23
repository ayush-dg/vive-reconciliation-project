## G09 — lakehouse connection
ID: M-033
Layer: infra
Source file: src/lakehouse/connection.py

**Module** — lakehouse connection
**ID** — M-033
**Layer** — infra
**Primary Responsibility** — The single file that knows the storage backend (SQLite locally/tests, Azure SQL in production via `pyodbc`) — every other module gets a connection from here and writes backend-agnostic SQL.

**Inputs** — `execute_sql(sql, params=None)`, `execute_query(sql, params=None)` — raw SQL strings + positional params from every calling module.

**Outputs** — `execute_sql()` returns a cursor; `execute_query()` returns `list[dict]` (rows).

**Public Interface**
- `get_connection()` — returns a live connection, backend chosen by `_using_azure_sql()`.
- `execute_sql(sql, params=None)`
- `execute_query(sql, params=None)`
- `_using_azure_sql()` (private) — `bool(os.getenv("AZURE_SQL_SERVER"))`
- `_translate_for_azure(sql)` (private) — rewrites `INSERT OR REPLACE` → `MERGE`, trailing `LIMIT n` → `SELECT TOP n`.
- `_is_dropped_connection_error(exc)` (private), `_run_with_retry(fn)` (private)

**Error Behaviour**
- **Deliberate, narrow retry**: `_run_with_retry()` retries up to `MAX_CONNECTION_RETRIES=3` times, waiting `CONNECTION_RETRY_WAIT_SECONDS=5`, *only* for pyodbc SQLSTATE `08S01`/`08001` (dropped/timed-out connection — confirmed by source, matches Azure SQL serverless auto-pause behavior described in the module docstring). Any other exception (a genuine query/schema error, or any SQLite error) propagates on the first attempt, unretried.
- **`_translate_for_azure()`'s `INSERT OR REPLACE` rewrite raises `NotImplementedError`** for any table not listed in `AZURE_UPSERT_KEYS` (`{"silver_reconciliation_standard": ["record_id"], "extraction_cache": ["document_hash", "statement_id"]}`) — a deliberate fail-loud guard, not swallowed. Confirmed: exactly 2 tables registered; any new `INSERT OR REPLACE` call site targeting a third table would raise this immediately on first Azure SQL use, not silently misbehave.

**Known Fragility**
- **`_INSERT_OR_REPLACE_RE`/`_TRAILING_LIMIT_RE` are narrow regexes, not a general SQL parser** (module docstring says so explicitly, confirmed by reading the actual patterns) — they only handle the exact two SQLite-specific constructs this codebase currently uses. A new call site using a different SQLite-only construct (e.g. `INSERT OR IGNORE`, a bound `LIMIT ?` placeholder — see M-011's `get_recent_runs()` working around exactly this) would not be translated and would fail against Azure SQL with a T-SQL syntax error, not a clean, early error.
- `get_recent_runs()` (M-011) already documents having to route around the `LIMIT` translator's exact-literal requirement — confirms this limitation is a real, already-encountered constraint, not theoretical.

**Change Impact** — Every module in the system that touches the database depends on this module. A new SQLite-specific SQL construct introduced anywhere requires either avoiding it or adding a new translation pattern here.

**Callers** — M-011, M-013 (indirectly via M-011), M-014, M-016, M-017, M-019, M-032, M-035, M-036, M-037, M-041, M-042 (every module that reads/writes the lakehouse database)
**Calls** — none (bottom of the call graph for DB access)
**Integration Points Used** — IP-008 (Lakehouse database)
