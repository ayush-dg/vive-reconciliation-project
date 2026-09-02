**Module:** session.ts
**ID:** M-004
**Layer:** infra
**Primary Responsibility:** Signs and verifies HMAC-SHA256 session cookie tokens using Edge-runtime-safe Web Crypto APIs, and defines the session cookie's policy and idle-timeout rules.

**Inputs:**
- `payload: SessionPayload` (`signSessionToken`) — `{ userId: string; username: string; lastSeenAt: number }`.
- `token: string | undefined` (`verifySessionToken`) — the raw cookie value.
- `payload: SessionPayload`, `now?: number` (`isSessionExpired`).
- Env var `SESSION_SECRET` (required — signing/verification key material).
- Env var `SESSION_IDLE_TIMEOUT_MS` (optional override; documented as test-only, e.g. `ui_tests/sign-in.spec.ts`).
- Env var `NODE_ENV` (`sessionCookieOptions`'s `secure` flag).

**Outputs:** `signSessionToken` returns a `payloadB64.sigB64` string. No I/O side effects — pure crypto/string transforms throughout.

**Public Interface:**
- `SESSION_COOKIE_NAME: 'vive_session'` (const)
- `sessionCookieOptions(): { httpOnly: true; sameSite: 'lax'; path: '/'; secure: boolean }`
- `getIdleTimeoutMs(): number`
- `type SessionPayload = { userId: string; username: string; lastSeenAt: number }`
- `signSessionToken(payload: SessionPayload): Promise<string>`
- `verifySessionToken(token: string | undefined): Promise<SessionPayload | null>`
- `isSessionExpired(payload: SessionPayload, now?: number): boolean`

**Error Behaviour:**
- `signSessionToken`: `getSigningKey()` rejects if `SESSION_SECRET` is unset (explicit thrown `Error`, propagates as a rejected promise) — not caught in this module.
- `verifySessionToken`: the entire verify+decode path is wrapped in one try/catch — ANY failure (missing `SESSION_SECRET`, malformed base64, invalid HMAC signature, malformed/incomplete JSON payload) returns `null` rather than throwing or distinguishing the failure reason.
- `isSessionExpired`: pure arithmetic, never throws.

**Known Fragility:**
- `verifySessionToken` collapses a server misconfiguration (`SESSION_SECRET` not set in the deployment env) into the exact same `null` result as a tampered, expired, or simply absent cookie — there is no way for a caller to tell "user isn't logged in" apart from "the server is misconfigured" from this function's return value alone.
- The Edge/Node dual-runtime constraint is load-bearing and non-obvious: this file deliberately avoids `node:crypto`/`Buffer` in favor of Web Crypto (`crypto.subtle`, `btoa`/`atob`) specifically so `src/proxy.ts` (Edge middleware) can import it directly. A future edit reaching for `Buffer` or `node:crypto` here would silently break the Edge middleware build/runtime.
- `isSessionExpired` only checks idle timeout via `lastSeenAt`; there's no absolute session lifetime. Whatever code refreshes `lastSeenAt` on each request (believed to be `proxy.ts`, not in this file) is a coupling invisible from this module alone — a bug there could make sessions effectively never expire.
- `SESSION_IDLE_TIMEOUT_MS` is documented as intended only for test runs, but nothing in code prevents it from being set in a real deployment, which would silently change a security-relevant timeout.

**Change Impact:** Direct callers M-002 and M-043; `src/proxy.ts` (Edge middleware, not in the numbered call table) is also a documented consumer. Any change to `SessionPayload`'s shape or to `SESSION_COOKIE_NAME` must be propagated to all three consumers by hand.

**Callers:** M-002, M-043
**Calls:** None
**Integration Points Used:** None
