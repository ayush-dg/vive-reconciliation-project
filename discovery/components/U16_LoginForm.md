**Module:** LoginForm
**ID:** M-063
**Layer:** component
**Primary Responsibility:** Client-side sign-in form that submits username/password via a React Server Action and surfaces the resulting auth error inline.

**Inputs (Props):** None (no props — reads no external state besides its own form action).
**Outputs (Rendered UI + Side Effects):** Renders a `<form action={formAction}>` with username/password fields, a submit button (disabled while pending, via `useFormStatus`), an inline `role="alert"` error message when `state.error` is set, a disabled "Sign in with company SSO" button (`title="Coming soon"`), and a disabled "Contact IT" link (`onClick` calls `preventDefault`). Side effect: submitting the form invokes `loginAction` (M-054) via `useActionState`, which performs the actual authentication (cookie write presumably happens inside M-054, not observable here) and returns `LoginState`.
**State Consumed:** None (no store/context reads) — local `useActionState` state (`{ error: string | null }`) is component-local, not a shared store.
**Public Interface:** `export default function LoginForm()`; internal (non-exported) `SubmitButton()` sub-component using `useFormStatus`.
**Error Behaviour:** On failed login, `state.error` is populated by `loginAction` (M-054) and rendered inline as `<p role="alert" data-testid="sign-in-error">`; the form does not throw or redirect on failure — it stays on `/login` with the error visible. On success, `loginAction` presumably redirects (its internals are out of scope, M-054).
**Known Fragility:** SSO button and "Contact IT" link are permanently disabled/inert placeholders (`disabled` attribute, `preventDefault` no-op) — easy for a future engineer to assume they're wired up and "fix" the wrong thing, or conversely to leave them disabled forever without noticing they were meant as a stub. `initialState` is a module-level constant object reused across renders/instances — fine since it's read-only and React only uses it as the initial value.
**Change Impact:** Changing the form field `name` attributes (`username`, `password`) would break `loginAction` (M-054) if it reads `FormData` by those same keys — tight but undeclared coupling. Removing `useActionState`/`formAction` would break the entire sign-in flow.
**Callers:** M-062 (LoginPage) renders this.
**Calls:** M-054 (login/actions.ts `loginAction`, via `useActionState` at LoginForm.tsx:19).
**Integration Points Used:** None (fetches internal API routes only) — N/A; uses a Server Action, not a fetch call.
