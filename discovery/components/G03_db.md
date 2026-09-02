**Module:** db.ts
**ID:** M-003
**Layer:** infra
**Primary Responsibility:** Environment-variable-driven database connection layer that selects and provides either a local SQLite handle or a Fabric SQL connection pool, and exposes connectivity/lifecycle helpers.

**Inputs:**
- Env var `FABRIC_SQL_ENDPOINT` — presence alone determines `getDbMode()`'s result ('fabric' vs 'sqlite'); also used as the connection string for `new sql.ConnectionPool(endpoint)`.
- Env var `SQLITE_DB_PATH` (optional, default `./.data/recon.local.db`) — resolved against `process.cwd()`.
- `process.cwd()` — implicit input to `getSqlitePath()`; different launch directories yield different DB files.

**Outputs:**
- Module-level singleton `sqliteInstance: Database.Database | null` — created once, reused for process lifetime.
- Module-level singleton `fabricPoolPromise: Promise<sql.ConnectionPool> | null` — created once, cached (including if it later rejects — see fragility).
- Side effect: `fs.mkdirSync(dirname, { recursive: true })` creates the `.data` directory and the SQLite file on first `getSqliteDb()` call.
- `pingDb()` executes `SELECT 1` against whichever backend is active. `closeDb()` closes and nulls out both singletons.

**Public Interface:**
- `type DbMode = 'fabric' | 'sqlite'`
- `getDbMode(): DbMode`
- `getSqliteDb(): Database.Database`
- `getFabricPool(): Promise<sql.ConnectionPool>`
- `pingDb(): Promise<{ mode: DbMode; ok: boolean }>`
- `closeDb(): Promise<void>`

**Error Behaviour:**
- `getDbMode()` never throws.
- `getSqliteDb()`: `fs.mkdirSync`/`new Database(...)` can throw synchronously (permissions, disk issues) — uncaught, propagates to caller.
- `getFabricPool()`: throws an explicit `Error` if `FABRIC_SQL_ENDPOINT` is unset, even though this is meant to be guarded by callers checking `getDbMode()` first — nothing enforces that ordering; calling it directly without the check just gets a clear thrown error instead of a silent fallback.
- `pingDb()`: no try/catch of its own — the comment's "never throws on a merely-unset env var" refers only to the mode-selection fallback, not to actual connectivity failures, which propagate uncaught.
- `closeDb()`: no error handling around `pool.close()`; propagates.

**Known Fragility:**
- **[NOTABLE]** `fabricPoolPromise` is assigned synchronously (`fabricPoolPromise = new sql.ConnectionPool(endpoint).connect()`) before the connect resolves. If the connect attempt fails, the now-*rejected* promise stays cached in the module-level variable — every subsequent `getFabricPool()` call returns that same rejected promise forever, with no retry, until `closeDb()` is explicitly called to reset it. A transient Fabric connectivity blip at startup could therefore permanently break Fabric-mode DB access for the life of the process.
- `getSqlitePath()` resolves relative to `process.cwd()` at call time — launching the process from a different working directory silently creates/uses a different DB file (flagged explicitly in the source comment as a known local-dev-only limitation).
- `turbopackIgnore` annotations on the dynamic path resolution are load-bearing for the Next.js build's output file tracing — removing them risks breaking production builds, per the inline comments.
- WAL journal mode and `foreign_keys = ON` are set only once, at `getSqliteDb()`'s first call — any other process or tool opening the same `.db` file without these pragmas could behave inconsistently (e.g., FK enforcement not applied).

**Change Impact:** The most depended-upon infra module in the whole graph — 20 distinct callers per the Internal Call Table. Any signature change to `getDbMode`/`getSqliteDb`/`getFabricPool` ripples through nearly every domain module. The `if (mode === 'sqlite') {...} else {...}` two-branch pattern is duplicated verbatim across many callers (auth.ts, migrate.ts, vendorSchema.ts, etc.) rather than centralized — adding a third `DbMode` value would require auditing every one of those call sites individually, since none use an exhaustiveness check.

**Callers:** M-001, M-007, M-011, M-012, M-013, M-014, M-015, M-016, M-017, M-018, M-019, M-020, M-021, M-022, M-024, M-025, M-026, M-027, M-041, M-051
**Calls:** None (uses the `better-sqlite3` and `mssql` packages directly, not other numbered modules)
**Integration Points Used:** IP-002 (Fabric SQL `recon` database), IP-004 (Fabric Warehouse `silver`/`gold`, write path)
