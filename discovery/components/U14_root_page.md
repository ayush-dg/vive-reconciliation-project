**Module:** Root Page
**ID:** M-061
**Layer:** page
**Primary Responsibility:** Unconditionally redirects the unauthenticated app root (`/`) to `/login`.

**Inputs (Props):** None (no params, no searchParams accessed).
**Outputs (Rendered UI + Side Effects):** Renders nothing — calls `redirect('/login')` from `next/navigation`, which throws a Next.js redirect signal and never returns UI. Side effect: HTTP redirect to `/login` on every request to `/`.
**State Consumed:** None.
**Public Interface:** `export default function RootPage()`.
**Error Behaviour:** N/A — `redirect()` is Next.js's own control-flow mechanism (throws internally, caught by the framework), not an application error path.
**Known Fragility:** `[NOTABLE]` This route performs no auth check of its own — it redirects everyone to `/login` regardless of session state, relying entirely on `/login`'s own page (or middleware/proxy, per M-064's comment referencing `proxy.ts`) to send an already-authenticated user onward. If that downstream logic is ever removed, an authenticated user hitting `/` would be bounced to `/login` unnecessarily. `NOT DETERMINABLE FROM SOURCE` whether `/login/page.tsx` (M-062) itself checks for an existing session — it does not in the source read for this module set.
**Change Impact:** Any change to the target path breaks the app's entire "unauthenticated landing" behavior — this is the only line of logic in the module.
**Callers:** Framework-invoked (Next.js router) for GET `/`; not imported by other modules.
**Calls:** None.
**Integration Points Used:** None (fetches internal API routes only) — N/A, no fetch at all; uses `next/navigation`'s `redirect`.
