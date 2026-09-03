**Module:** App Layout (authenticated shell)
**ID:** M-064
**Layer:** layout
**Primary Responsibility:** Server-rendered authenticated shell — verifies a session exists (defensive check), then wraps every `(app)` route's content with the Sidebar and Toast host.

**Inputs (Props):** `{ children: React.ReactNode }`.
**Outputs (Rendered UI + Side Effects):** Renders `<div className="app-shell">` containing `<Sidebar username={session.username} />` (M-082), `<main className="app-main">{children}</main>`, and `<ToastProvider />` (M-083). Side effect: if no session is found, calls `redirect('/login')` (Next.js control-flow throw) — per the source comment, this is a defensive fallback, since `proxy.ts` is expected to have already redirected unauthenticated requests before reaching this layout.
**State Consumed:** None (session is read once server-side, not a client store).
**Public Interface:** `export default async function AppLayout({ children }: { children: React.ReactNode })` — async Server Component.
**Error Behaviour:** No try/catch around `getCurrentSession()` — if it throws, the error propagates to `(app)/error.tsx` (M-066), the nearest error boundary. If it resolves to a falsy session, redirects rather than erroring.
**Known Fragility:** `[NOTABLE]` This is a "defensive fallback, not the primary enforcement point" per its own comment — actual access control is expected to live in `proxy.ts` (out of this session's scope). If `proxy.ts` is ever removed or misconfigured, this layout is the only remaining backstop, and every route under `(app)` (home, upload, exceptions, documents) depends on it being correct. `session.username` is passed to Sidebar without any fallback for an empty/malformed username.
**Change Impact:** This layout wraps every route in the `(app)` group — any change to session-check logic, or to what's rendered around `{children}`, affects Home, Upload, Exceptions, Document Detail, and all dev-test-* pages simultaneously. Removing `ToastProvider` here would silently break toast notifications for every downstream page that calls `useToast()` (M-068, M-070, M-074 via note-save flows are not toast-based but M-076, M-079 all rely on it).
**Callers:** Framework-invoked for all routes under `(app)`; not imported elsewhere.
**Calls:** M-002 (`getCurrentUser`/`currentUser.ts`'s `getCurrentSession`, at layout.tsx:11).
**Renders:** M-082 (Sidebar), M-083 (ToastProvider), + `{children}`.
**Integration Points Used:** None (fetches internal API routes only) — N/A; calls a server-side lib function, not a fetch.
