**Module:** auth.ts
**ID:** M-001
**Layer:** infra
**Primary Responsibility:** Hashes/verifies user passwords with scrypt and looks up app users by username, across both SQLite and Fabric DB backends.

**Inputs:**
- `password: string`, `stored: string` — plaintext password and stored `"salt:hash"` string (`verifyPassword`), no format validation beyond the split.
- `password: string` — plaintext password to hash (`hashPassword`), no length/complexity validation.
- `username: string` — lookup key (`findUserByUsername`), passed straight into a parameterized query (sqlite: `?`; fabric: `@username`) — no app-level validation.
- Implicitly depends on `getDbMode()`/`getSqliteDb()`/`getFabricPool()` (M-003) for the DB branch taken.

**Outputs:**
- `hashPassword` returns a new `"${salt}:${hash}"` hex string (16-byte random salt, 64-byte scrypt key). No I/O.
- `verifyPassword` returns `boolean`. No I/O.
- `findUserByUsername` returns `AppUser | null` (read-only `SELECT` against `recon_app_user` / `recon.app_user`); no writes.

**Public Interface:**
- `hashPassword(password: string): string`
- `verifyPassword(password: string, stored: string): boolean`
- `type AppUser = { userId: string; username: string; passwordHash: string; displayName: string | null }`
- `findUserByUsername(username: string): Promise<AppUser | null>`

**Error Behaviour:**
- `hashPassword`/`verifyPassword` are synchronous with no try/catch — any `crypto` exception propagates directly to the caller.
- `verifyPassword` defensively returns `false` (not a throw) if `stored` doesn't split into `salt:hash`, or if the derived key length differs from the stored hash's length — avoids a `timingSafeEqual` length-mismatch exception, fails closed.
- `findUserByUsername` has no try/catch of its own; any DB error (connection failure, query error) from `getSqliteDb()`/`getFabricPool()`/the query itself propagates as a rejected promise straight to the caller, uncaught.

**Known Fragility:**
- Explicitly Node-runtime only per the file's own header comment — must never be imported from `src/proxy.ts` (Edge runtime); doing so would break on `node:crypto`. `src/lib/session.ts` (M-004) is the Edge-safe half of auth by design.
- `SCRYPT_KEYLEN = 64` is hardcoded; changing it doesn't error loudly against old hashes — a length mismatch in `verifyPassword` just silently returns `false`, indistinguishable from a genuinely wrong password.
- The sqlite/fabric row-mapping logic is duplicated inline (same 4 fields mapped twice) rather than shared — a column rename applied to only one dialect's migration would silently diverge without a compile-time signal.

**Change Impact:** Only caller in the graph is M-054 (login flow). Any change to `AppUser`'s shape or to `hashPassword`'s output format also affects `scripts/seed_users.mjs` (outside the numbered module graph) which must independently produce compatible hashes.

**Callers:** M-054
**Calls:** M-003
**Integration Points Used:** None (M-003 is the one that talks to IP-002/IP-004, not this module directly)
