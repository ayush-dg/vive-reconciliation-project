**Module:** Login Page
**ID:** M-062
**Layer:** page
**Primary Responsibility:** Renders the sign-in screen shell (logo, heading, card chrome) around the interactive `LoginForm`.

**Inputs (Props):** None (no route params or searchParams consumed).
**Outputs (Rendered UI + Side Effects):** Renders a static `login-view`/`login-card` layout: Vive Collision logo image (`next/image`, `/vive-logo.png`, priority-loaded), heading/subtext, `<LoginForm />` (M-063), and a footer line. No side effects — pure server-rendered markup.
**State Consumed:** None.
**Public Interface:** `export default function LoginPage()`.
**Error Behaviour:** No error handling in this module — all interactive error states (bad credentials) live in `LoginForm` (M-063).
**Known Fragility:** Depends on `/vive-logo.png` existing in `public/`; a missing asset degrades gracefully (broken image icon) but is not guarded. Not a client component itself, so it stays server-rendered even though its child is a client component — standard Next.js composition, no special risk.
**Change Impact:** Cosmetic/structural changes only propagate to the sign-in screen; does not affect any other route. Removing `<LoginForm />` would leave the sign-in screen non-functional (no form to submit).
**Callers:** Framework-invoked for route `/login`; not imported elsewhere.
**Calls:** None directly (delegates all interactivity to M-063).
**Renders:** M-063 (LoginForm).
**Integration Points Used:** None (fetches internal API routes only) — N/A, no fetch in this module.
