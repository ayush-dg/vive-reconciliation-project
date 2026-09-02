**Module:** api/health/route.ts
**ID:** M-051
**Layer:** route
**Primary Responsibility:** Minimal health-check endpoint that exercises the env-var-driven DB connection (Fabric vs. local SQLite fallback) as a real, reachable request path, and is the one route explicitly excluded from the M-043 auth-proxy matcher (unauthenticated access is intentional).

**Inputs:** `GET()` — no params, no query, no body.
**Outputs:**
- 200: `{ mode: 'fabric'|'sqlite', ok: true }` (per `pingDb()` in M-003) — `ok` is always `true` on this path since `pingDb` only returns normally when its connectivity check (a trivial `SELECT 1`) succeeds.
- 503: `{ ok: false, error: string }` — `error` is `error.message` if `pingDb()` threw an `Error` instance, else `String(error)`. This is the only route in this session's set that explicitly catches and translates an underlying failure into a distinct non-200/non-404/409 status (503, not 500).
**Public Interface:**
`export async function GET(): Promise<NextResponse>`
**Error Behaviour:** Explicit try/catch around the single `await pingDb()` call — any thrown error (DB unreachable, Fabric connection failure, SQLite file/lock issue) is caught and converted to a 503 with the error message surfaced directly in the response body. This is the only one of the 12 route modules in this session whose entire body is a deliberate try/catch translating a downstream failure into a meaningful status code rather than letting it fall through to an unhandled 500.
**Known Fragility:** The 503 response includes the raw underlying error message (`error.message`) with no redaction — for `sqlite` mode this is likely benign (local file path issues), but for `fabric` mode a connection-string or auth failure message could leak infrastructure details (e.g. hostname, driver-level error text) to an unauthenticated caller, since this route is deliberately excluded from the M-043 auth gate. NOT DETERMINABLE FROM SOURCE whether any monitoring/alerting actually consumes this endpoint's specific shape — no caller of `/api/health` exists anywhere in this codebase's own call graph (confirmed via A02's roster — no M-NNN module fetches it); it exists purely as an externally-pollable endpoint.
**Change Impact:** This is the sole route explicitly carved out of `proxy.ts`'s (M-043) auth matcher (`/((?!login|api/health|...)...)`) — any change to this route's path would require a corresponding update to that regex or the route would become auth-gated unexpectedly. Its output shape mirrors `pingDb()` (M-003) directly; a change to `DbMode` or `pingDb`'s return shape flows straight through unmodified.
**Callers:** None within this codebase's traced call graph — reachable only via direct external HTTP request (e.g. an uptime monitor), consistent with its purpose as an unauthenticated health probe.
**Calls:** M-003 (`src/app/api/health/route.ts:9`)
**Integration Points Used:** None (routes through serving-layer modules) — M-051 calls M-003 (an infra module) directly rather than a serving-layer module, but per the reference data this is still not an IP itself; M-003 is the module that owns IP-002/IP-004.
