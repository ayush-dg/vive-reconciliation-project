## G01 — Lakehouse Connection
ID: M-037
Layer: infra
Source file: `src/lakehouse/connection.py`

**Module** — Lakehouse Connection
**ID** — M-037
**Layer** — infra
**Primary Responsibility** — The single storage-backend abstraction point. Selects SQLite (local/dev/test) or Azure SQL (production) based on `AZURE_SQL_SERVER`; additionally provides a parallel Fabric Warehouse path for three cut-over tables.

**Inputs** — `AZURE_SQL_SERVER`/`AZURE_SQL_DATABASE`/`AZURE_SQL_USERNAME`/`AZURE_SQL_PASSWORD` (Azure SQL path); `FABRIC_SQL_ENDPOINT`/`FABRIC_WAREHOUSE_NAME`/`FABRIC_TENANT_ID`/`FABRIC_WORKSPACE_ID` (Fabric path, requires an existing `az login` session); raw SQL + params from every caller.

**Outputs** — Query results (list of dicts) or execution cursors, against whichever backend is configured.

**Public Interface**
- `get_connection()` — Azure SQL or SQLite, selected by `_using_azure_sql()`.
- `get_fabric_connection()` — Fabric Warehouse (Azure CLI token auth) or **the same local SQLite `DB_PATH`** as `get_connection()` when Azure SQL isn't configured — a deliberate test-isolation convention, not a separate database.
- `execute_sql(sql, params=None)`, `execute_query(sql, params=None)` — Azure SQL/SQLite path, with dialect translation (`_translate_for_azure()`) and connection-drop retry (`_run_with_retry()`, up to 3 retries on SQLSTATE 08S01/08001).
- `execute_sql_fabric(sql, params=None)`, `execute_query_fabric(sql, params=None)` — Fabric path. **No dialect translation, no drop-retry** — callers must write SQL valid on both SQLite and T-SQL.
- `_using_azure_sql()`, `_using_fabric_warehouse()` (the latter defined but its actual call sites were not traced this session — worth confirming in a follow-up read).

**Error Behaviour** — `execute_sql`/`execute_query` retry transparently on a dropped Azure SQL connection, then re-raise unchanged on any other error or once retries are exhausted. `execute_sql_fabric`/`execute_query_fabric` have zero retry logic — any connection or query error propagates immediately to the caller.

**Known Fragility**
- **The Fabric-cut-over tables' `id` columns have no `IDENTITY` on the Fabric side** — every caller writing to `extraction_cache`, `document_intake_log`, or `validation_document_review_queue` via the Fabric functions computes `MAX(id) + 1` in Python (confirmed at each call site in M-017 and M-003) — not concurrency-safe. See `TOPOLOGY.md` A01 row 8.
- `get_fabric_connection()`'s fallback-to-SQLite behavior is easy to misread as a bug (why does a "Fabric" function open a SQLite connection?) — it is deliberate, per this file's own inline comment, specifically to preserve the existing `AZURE_SQL_SERVER=""` test-isolation convention that predates the Fabric cut-over. A future engineer "fixing" this to always reach real Fabric would break every existing test that relies on that fallback for isolation.
- `_translate_for_azure()` is a narrow, two-pattern translator (`INSERT OR REPLACE` → `MERGE`; trailing `LIMIT` → `SELECT TOP`) — not a general SQL dialect translator. Any new SQLite-specific syntax introduced elsewhere in the codebase that isn't one of these two patterns will fail silently differently on Azure SQL than on SQLite, with no translation layer to catch it.
- `AZURE_UPSERT_KEYS` must be updated by hand whenever a new `INSERT OR REPLACE INTO` call site targets a table not already listed — `_translate_for_azure()` raises `NotImplementedError` if it isn't, which is at least a loud failure, not silent.

**Change Impact** — The single highest-blast-radius module in the codebase — called, directly or transitively, by nearly every other module (M-003, M-016, M-017, M-020, M-034, M-035, M-039, M-040, M-045, M-046). Any change to connection selection, retry behavior, or dialect translation affects the entire system's data layer.

**Callers** — M-003, M-016, M-017, M-020, M-034, M-035, M-039, M-040, M-045, M-046
**Calls** — none (leaf infra module)
**Integration Points Used** — IP-008 (Azure SQL/SQLite), IP-011 (Fabric Warehouse)
