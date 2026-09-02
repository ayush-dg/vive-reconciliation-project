**Module:** currentUser.ts
**ID:** M-002
**Layer:** infra
**Primary Responsibility:** Server Component/Server Action helper that resolves the current authenticated user's session payload from the request's cookie jar.

**Inputs:** None as parameters — reads the session cookie (`SESSION_COOKIE_NAME` from M-004) via `next/headers`'s `cookies()`, which is itself bound to the current request context.

**Outputs:** `SessionPayload | null`. No mutation, no I/O beyond the cookie read.

**Public Interface:**
- `getCurrentSession(): Promise<SessionPayload | null>`

**Error Behaviour:** No try/catch in this file itself. Delegates entirely to `verifySessionToken` (M-004), which internally catches all crypto/parsing failures and returns `null` — so `getCurrentSession()` effectively never rejects for a missing/malformed/tampered/expired-signature cookie, it just resolves `null`. It would only reject if `cookies()` itself throws (e.g., invoked outside a valid request context).

**Known Fragility:**
- The file's own comment states routes under `src/app/(app)/` are guarded by `proxy.ts`, and a `null` result here "would indicate the guard was bypassed" — but nothing in this function enforces that; it's purely documentation. A new route that forgets proxy guarding renders for an unauthenticated caller unless the page itself explicitly checks for `null`.
- Deliberately NOT used from `src/proxy.ts` (Edge middleware reads `request.cookies` directly instead of `next/headers`) — this creates a conceptual (not code) duplication between two cookie-reading paths; any change to `SESSION_COOKIE_NAME` or the cookie payload shape must be kept in sync with proxy.ts by hand, with no shared enforcement.

**Change Impact:** Sole caller M-064. Any change to `verifySessionToken`'s return contract or `SESSION_COOKIE_NAME` (both in M-004) breaks this silently (returns `null` instead of a session) rather than throwing — could read as "user logged out" everywhere M-064 relies on it.

**Callers:** M-064
**Calls:** M-004
**Integration Points Used:** None
