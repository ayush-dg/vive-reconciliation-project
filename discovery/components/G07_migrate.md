**Module:** migrate.ts
**ID:** M-007
**Layer:** infra
**Primary Responsibility:** Idempotently applies pending local SQLite migration files in filename order, tracked via a bookkeeping table; in Fabric mode, deliberately refuses to run and instead throws instructions for applying migrations externally via `sqlcmd`.

**Inputs:** No function parameters. Reads `migrations/*.sql` and `migrations/*.sqlite.sql` files from disk (`MIGRATIONS_DIR = process.cwd()/migrations`); depends on `getDbMode()`/`getSqliteDb()` (M-003).

**Outputs (sqlite mode):**
- Creates the `_migrations` bookkeeping table if absent (`filename TEXT PRIMARY KEY, applied_at TEXT`).
- For each not-yet-applied `.sqlite.sql` file (sorted by filename), executes its full SQL text via `db.exec(sql)` and inserts a bookkeeping row, both inside one `db.transaction(...)` per file — real schema/data mutations against the live SQLite DB.
- Returns `{ applied: string[]; skipped: string[] }`.

**Outputs (fabric mode):** No DB mutation — throws before touching the database.

**Public Interface:**
- `runMigrations(): { applied: string[]; skipped: string[] }`

**Error Behaviour:**
- Fabric mode: throws synchronously, listing every pending Fabric migration file with the exact `sqlcmd` command needed to apply it — deliberate design, no application-layer execution attempted.
- SQLite mode: each file's `db.exec(sql)` + bookkeeping insert runs inside `db.transaction(() => {...})`; if the migration SQL fails partway, better-sqlite3 rolls back that whole transaction and the thrown error propagates uncaught out of `runMigrations()`, aborting the loop — later migration files in the list are never attempted, and the failing file is correctly left unmarked in `_migrations` (fail-fast, no explicit cleanup messaging beyond the raw exception).

**Known Fragility:**
- Migration ordering is driven purely by filename string-sort (`.sqlite.sql` suffix filter + `.sort()`) — there is no explicit ordinal/version check beyond that; a misnamed or out-of-sequence file would silently apply in the wrong order.
- Calling `runMigrations()` unconditionally at boot (without checking `getDbMode()` first) crashes the app in Fabric mode by design (throws). Per the Internal Call Table, **no numbered module calls M-007** — it's invoked externally by `scripts/migrate.mjs` and referenced by `ui_tests/global-setup.ts` (confirmed via source grep), i.e. as a standalone script/test-setup step outside the application runtime.
- The `_migrations` bookkeeping table has no tamper protection — manually deleting a row would cause that migration to silently re-attempt, and would likely fail with a "table already exists"-class error since only the bookkeeping table's own `CREATE TABLE IF NOT EXISTS` is idempotent; individual migration files' own statements are not guaranteed idempotent.

**Change Impact:** Governs the actual local-dev/demo SQLite schema. A bug here corrupts or fails to advance that schema, with blast radius across every module that queries tables the migrations create (i.e., effectively all of M-003's SQLite consumers) — even though M-007 itself has zero direct callers in the numbered module graph.

**Callers:** None in the Internal Call Table (invoked externally via `scripts/migrate.mjs` and test setup, outside the numbered module graph — confirmed via grep)
**Calls:** M-003
**Integration Points Used:** None (the Fabric path deliberately delegates to external `sqlcmd`, not an in-app IP call)
