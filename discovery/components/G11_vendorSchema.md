**Module:** vendorSchema.ts
**ID:** M-041
**Layer:** infra
**Primary Responsibility:** Idempotently generates and executes the per-vendor raw statement table (plus an append-only-enforcement trigger) DDL, for both Fabric and SQLite dialects, at the point a new vendor is first registered at runtime.

**Inputs:**
- `vendorSlug: string` — passed to `ensureVendorStmtTable` and, internally, to `vendorStmtTableDdlFabric`/`vendorStmtTableDdlSqlite`; validated transitively via M-006's `vendorStmtTableName()` -> `assertValidVendorSlug()`.
- Implicitly depends on `getDbMode()`/`getSqliteDb()`/`getFabricPool()` (M-003) and `vendorStmtTableName()` (M-006).

**Outputs:** Real DDL side effects: creates a new table — `extracted.stmt_<slug>` (fabric) or `extracted_stmt_<slug>` (sqlite) — plus a corresponding `UPDATE`-blocking trigger (`RAISERROR`+`ROLLBACK` on fabric; `RAISE(ABORT, ...)` on sqlite), executed via `pool.request().batch()` (fabric) or `db.exec()` (sqlite). Returns the created table's fully-qualified name.

**Public Interface:**
- `ensureVendorStmtTable(vendorSlug: string): Promise<string>`
- (`vendorStmtTableDdlFabric`/`vendorStmtTableDdlSqlite` are internal, not exported.)

**Error Behaviour:** `ensureVendorStmtTable` has no try/catch of its own. `vendorStmtTableName()`'s internal `assertValidVendorSlug()` (M-006) can throw synchronously before any DB call is made for an invalid slug. `db.exec()`/`pool.request().batch()` failures propagate uncaught as a rejected promise — see fragility below for a specific case where this is expected to fire.

**Known Fragility:**
- **[NOTABLE latent bug]** Dialect asymmetry in idempotency: the SQLite DDL uses `CREATE TABLE IF NOT EXISTS` / `CREATE TRIGGER IF NOT EXISTS` (genuinely idempotent — repeat calls are no-ops), but the Fabric DDL's `CREATE TABLE`/`CREATE TRIGGER` statements have **no `IF NOT EXISTS` guard at all**. Calling `ensureVendorStmtTable()` twice for the same `vendorSlug` in fabric mode would throw ("table already exists") on the second call — directly contradicting the function's own doc comment ("Idempotently creates the raw table"). Currently unreachable in practice since Fabric app-state is not actually implemented elsewhere in the app (per M-003's comments, every other module hard-throws in fabric mode) — but a real bug waiting to surface if that changes.
- This file has no independent slug validation of its own — it relies entirely on M-006's `assertValidVendorSlug()` being called (transitively, via `vendorStmtTableName()`) before any string interpolation into DDL text, and on that regex never being loosened. There is no direct/explicit call to `assertValidVendorSlug` visible in this file itself.
- The append-only trigger is the *only* enforcement of the "no application-layer UPDATE path" invariant (matching `extracted.extraction_attempt`'s discipline, per the comment). If any future migration or manual DDL operation drops/recreates a vendor table without recreating the trigger, that invariant silently disappears with no other code-level check to catch it.

**Change Impact:** Sole caller M-021. Vendor tables created under an earlier version of this DDL keep their original schema even after this file's DDL logic changes — there is no versioning or backfill mechanism inside this module, so schema drift across vendors registered at different times is possible with no built-in detection.

**Callers:** M-021
**Calls:** M-006, M-003
**Integration Points Used:** None
