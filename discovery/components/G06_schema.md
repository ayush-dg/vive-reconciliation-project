**Module:** schema.ts
**ID:** M-006
**Layer:** infra
**Primary Responsibility:** Resolves dialect-specific (Fabric vs SQLite) qualified table names and validates vendor slugs used to safely build per-vendor table/trigger names for DDL generation.

**Inputs:**
- `schema: string, table: string, mode: DbMode` (`qualifiedTableName`) — no validation performed on `schema`/`table`.
- `vendorSlug: string` (`assertValidVendorSlug`, `vendorStmtTableBaseName`, `vendorStmtTableName`) — validated against `VENDOR_SLUG_PATTERN = /^[a-z][a-z0-9_]{0,62}$/` (module-internal, not exported).
- `mode: DbMode` (`vendorStmtTableName`).

**Outputs:** Pure string-returning functions; no I/O, no mutation, no side effects.

**Public Interface:**
- `qualifiedTableName(schema: string, table: string, mode: DbMode): string`
- `assertValidVendorSlug(vendorSlug: string): void` (throws on invalid input; no return value on success)
- `vendorStmtTableBaseName(vendorSlug: string): string`
- `vendorStmtTableName(vendorSlug: string, mode: DbMode): string`

**Error Behaviour:** `assertValidVendorSlug` throws a plain `Error` (embedding the regex in the message) if the slug fails the pattern. `vendorStmtTableBaseName`/`vendorStmtTableName` call it internally first, so they also throw synchronously on an invalid slug — uncaught here, propagates to the caller. `qualifiedTableName` never throws — it performs zero validation on its `schema`/`table` arguments.

**Known Fragility:**
- `qualifiedTableName` does **not** validate `schema` or `table` at all — only the vendor-slug path (`assertValidVendorSlug`) is guarded. The module's own comment frames slug validation as "a real trust boundary... enforced before the slug is ever interpolated into DDL text," but that protection only covers the vendor-slug functions; nothing structurally prevents an untrusted value reaching `qualifiedTableName` directly and bypassing it.
- `VENDOR_SLUG_PATTERN` is the *only* defense against DDL/SQL injection via vendor slug, because neither `better-sqlite3`'s `db.exec()` nor `mssql`'s `batch()` support parameterized identifiers for `CREATE TABLE`/`CREATE TRIGGER` (per the comment). This makes the regex itself security-critical — loosening it (allowing `-`, `.`, longer lengths, etc.) directly enlarges the DDL-injection surface used by M-041's generated `CREATE TABLE`/`CREATE TRIGGER` statements.
- The two dialect naming conventions (`schema.table` for fabric vs `schema_table` for sqlite) must stay conceptually reconciled with the actual migration files (`001_foundation_schema.sql` vs the `.sqlite.sql` variant, per the header comment) — nothing in code enforces that the two naming schemes actually match the real DDL; drift would surface only at query time, in one dialect only.

**Change Impact:** Callers M-021 and M-041. Since M-041 uses these functions to generate the actual `CREATE TABLE`/`CREATE TRIGGER` DDL, any change to the naming-convention logic changes table names for every vendor registered going forward while previously-created vendor tables keep their old names — a silent naming-scheme fork with no accompanying migration mechanism.

**Callers:** M-021, M-041
**Calls:** None
**Integration Points Used:** None
