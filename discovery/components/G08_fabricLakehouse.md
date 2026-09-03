**Module:** fabricLakehouse.ts
**ID:** M-008
**Layer:** infra
**Primary Responsibility:** Read-only client for the Fabric Lakehouse's `bronze.netsuite_vendorbill`/`bronze.netsuite_vendorcredit` reference tables, with vendor-scoped + amount-closest matching logic to check whether a statement line was actually posted in NetSuite while avoiding cross-vendor `tranid` collisions.

**Inputs:**
- Env vars: `FABRIC_CLIENT_ID`, `FABRIC_CLIENT_SECRET`, `FABRIC_TENANT_ID`, `FABRIC_LAKEHOUSE_SQL_ENDPOINT`, `FABRIC_LAKEHOUSE_NAME` (all required for `isFabricLakehouseConfigured()` to return `true`, and for `getAccessToken`/`runQuery` to function).
- `tranId: string`, `vendorNamePrefix: string | null`, `amount: number` (`getReferenceRowByTranId`, `getCreditRowByTranId`) — no validation performed, passed as parameterized query values.

**Outputs:** No writes anywhere — SELECT-only by explicit design comment. Returns `NetsuiteVendorBillRow | null`, or a watermark object. Side effects: caches an AAD access token in module-level `cachedToken`, reused across calls until ~60s before expiry; opens and closes one short-lived `tedious` `Connection` per query (no pooling).

**Public Interface:**
- `isFabricLakehouseConfigured(): boolean`
- `type NetsuiteVendorBillRow = { tranid: string; total: number; _run_id: string; _extracted_at: string; _source_system: string; rawFields: Record<string, unknown> }`
- `getReferenceRowByTranId(tranId: string, vendorNamePrefix: string | null, amount: number): Promise<NetsuiteVendorBillRow | null>`
- `getCreditRowByTranId(tranId: string, vendorNamePrefix: string | null, amount: number): Promise<NetsuiteVendorBillRow | null>`
- `getLatestReferenceWatermark(): Promise<Pick<NetsuiteVendorBillRow, '_run_id' | '_extracted_at' | '_source_system'> | null>`

**Error Behaviour:** `getAccessToken` throws an explicit `Error` if `credential.getToken()` returns falsy; `ClientSecretCredential` construction/token-acquisition failures (bad credentials, network) propagate as a rejected promise, uncaught here. `runQuery` wraps `tedious`'s callback API in a `Promise` — both the connection `'error'` event and the query callback's error reject the promise. Nothing in this module catches these anywhere — `findBillOrCreditRow`, `getReferenceRowByTranId`, `getCreditRowByTranId`, and `getLatestReferenceWatermark` all let errors propagate straight to the caller. `isFabricLakehouseConfigured` never throws (pure env-var presence check).

**Known Fragility:**
- Module-level `cachedToken` singleton with only a 60s expiry safety margin — relies on the AAD token's `expiresOnTimestamp` and local clock being accurate; a stale/skewed check could let an expired token reach `tedious` and fail mid-query rather than refreshing proactively.
- Deliberately uses a **separate** env var (`FABRIC_LAKEHOUSE_SQL_ENDPOINT`) from M-003's `FABRIC_SQL_ENDPOINT`, even though the comment confirms both resolve to the same physical hostname — consolidating them (a plausible "simplification") would flip `getDbMode()` into `'fabric'` app-state globally, which the comment explicitly warns breaks every other M-0xx module (none of which have Fabric app-state actually implemented, per M-003's own comments).
- Uses raw `tedious` instead of the `mssql` package specifically because `mssql`'s `ConnectionPool` does not follow Fabric's mid-handshake reroute to a `*.pbidedicated.windows.net` backend (confirmed by direct test — fails with "socket hang up"); reverting to `mssql` for consistency with db.ts would silently reintroduce that failure.
- No connection pooling — a new `tedious` `Connection` opens/closes per query, justified by expected low call volume ("at most once per statement line during a user-triggered Reconcile action"); a future bulk/batch reconciliation flow could turn this into a connection-storm/latency problem with no safety net in place.
- **[NOTABLE]** The vendor-scoped-then-amount-closest matching logic exists specifically to fix a confirmed real production bug (2026-08-31, Bald Hill Dodge statement matched against the wrong vendor's bill via `tranid` collision). The in-code comment explicitly warns that re-adding an unscoped fallback *after* a vendor-scoped search returns nothing would reopen that exact bug — a highly regressable piece of business logic.
- `rawFields` deliberately excludes the joined `bronze.netsuite_vendor` entity's own columns (2026-09-01 scope decision for the Exceptions screen) — a future engineer adding new evidence fields might expect vendor-entity fields to be present and be surprised they aren't.

**Change Impact:** Sole caller M-026. Any signature change to `getReferenceRowByTranId`/`getCreditRowByTranId` affects M-026's matching logic directly, and since this is the only live path to real NetSuite reference data, correctness regressions here directly affect reconciliation accuracy.

**Callers:** M-026
**Calls:** None (uses `tedious`/`@azure/identity` packages directly, not other numbered modules)
**Integration Points Used:** IP-003 (Fabric Lakehouse `bronze`)
