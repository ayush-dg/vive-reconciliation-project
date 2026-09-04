# ENH-002_BRIEF.md

**Enhancement ID:** ENH-002
**Title:** Fix live Fabric connection (FABRIC_SQL_ENDPOINT + connection-pool resilience)
**Author:** Vaishali
**Date:** 2026-09-03
**Status:** [x] Draft | [ ] AI Review Complete | [ ] Signed Off

---

## Enhancement Intent

This build's primary transactional store (`recon`, via `FABRIC_SQL_ENDPOINT`) cannot
currently connect to live Microsoft Fabric at all. Confirmed directly against source and
the real `mssql`/`@tediousjs/connection-string` parser, 2026-09-02: the configured value
is a bare hostname, not the ADO-style `Key=Value;...` connection string
`db.ts`'s `ConnectionPool` requires when given a string — it parses to an empty config,
no server, no auth, nothing. This compounds with a separate, independently-discovered bug:
a failed `.connect()` permanently caches the rejected promise in `db.ts`'s module-level
singleton, with no automatic retry until `closeDb()` is explicitly called. Together these
mean the very first live-Fabric connection attempt is guaranteed to fail, and that failure
then permanently breaks Fabric access for the life of the process. This enhancement fixes
both: reformats the connection string once an auth scheme is chosen, and makes the
connection pool recover from a transient failure instead of poisoning itself forever.

---

## Known Touch Points

| Touch Point | BCE Artifact | Entry |
|---|---|---|
| Fabric SQL connection pool (recon + silver writes) | MODULE_CONTRACTS.md | M-003 (db.ts) |
| Fabric SQL database (recon) — integration point | INTEGRATION_CONTRACTS.md | IP-002 |
| Fabric Warehouse (silver write path, same connection pool as IP-002) | INTEGRATION_CONTRACTS.md | IP-004 |
| Fabric Lakehouse (bronze) — reference pattern for a working AAD auth flow | MODULE_CONTRACTS.md / INTEGRATION_CONTRACTS.md | M-008 (fabricLakehouse.ts) / IP-003 |
| Connection-pool permanent-cache bug | RISK_REGISTER.md | R-004 |
| Malformed connection string, confirmed root cause | RISK_REGISTER.md | R-008 |

---

## Known Constraints

| Constraint | Type | Notes |
|---|---|---|
| Must decide the actual auth scheme before implementation | MANDATORY | Three real options exist and are not equivalent: SQL auth (credentials embedded in the connection string), Azure AD Managed Identity, or an explicit AAD service-principal flow matching `FABRIC_LAKEHOUSE_SQL_ENDPOINT`'s existing, already-working pattern (`FABRIC_CLIENT_ID`/`FABRIC_CLIENT_SECRET`/`FABRIC_TENANT_ID` via `ClientSecretCredential`, `fabricLakehouse.ts`). This is an infrastructure/ownership decision, not something resolvable by reading more source — needs input from whoever administers the Fabric SQL Database resource. |
| Must not touch the already-working Lakehouse (IP-003) auth path | MANDATORY | `fabricLakehouse.ts`'s AAD service-principal flow is confirmed correct and unrelated to this bug — this enhancement fixes IP-002/IP-004 only. |
| `closeDb()` retry-reset behavior | OPTIONAL | Current design requires an explicit `closeDb()` call to clear a poisoned pool. Phase 1 should decide whether the fix is automatic retry-with-backoff, or an operator-facing signal (log/alert) distinguishing "never configured" from "configured and broken," or both. |
| This is genuinely untested territory | MANDATORY | No session to date has run against live Fabric — Sessions 1-9 all built and tested against the local SQLite fallback. This enhancement will be the first real exercise of the Fabric code path; expect Phase 1 to surface things not visible from source alone. |

---

## Out of Scope

- Any change to the SQLite fallback path — this enhancement only touches the Fabric branch.
- The Lakehouse (bronze, IP-003) connection — already working, not touched.
- Migrating any other environment variable or Fabric resource beyond `FABRIC_SQL_ENDPOINT`
  and the connection-pool singleton behavior in `db.ts`.
- UI/application-level changes — this is purely an infrastructure/connection-layer fix.

---

## Engineer Sign-Off
[ ] I confirm this brief is accurate to my current understanding.
    Phase 1 may surface new information not reflected here.

**Signed:** _________________________
**Date:** ___________
