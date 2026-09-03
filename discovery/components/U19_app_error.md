**Module:** App Error Boundary (Next.js error.tsx)
**ID:** M-066
**Layer:** layout
**Primary Responsibility:** Global client-side error boundary for the `(app)` route group — catches render-time errors and shows an inline "Something went wrong" message with a Retry button instead of a full-page crash/redirect.

**Inputs (Props):** `{ error: Error & { digest?: string }; reset: () => void }` — the Next.js `error.tsx` convention's standard props.
**Outputs (Rendered UI + Side Effects):** Renders `<div className="error-boundary" role="alert" data-testid="error-boundary">` with a static message and a "Retry" button that calls `reset()` (Next.js's built-in re-render mechanism) on click. `error` itself is received but never displayed or logged in this component — no `console.error(error)`, no reporting call.
**State Consumed:** None.
**Public Interface:** `export default function AppError({ error, reset }: { error: Error & { digest?: string }; reset: () => void })`; marked `'use client'`.
**Error Behaviour:** This *is* the error-handling module — it activates when any render/throw occurs within the `(app)` route group's tree (e.g., M-073's "no exceptions for vendor" throw, M-075's "document not found" throw). It does not distinguish error types or messages — every thrown error gets the same generic "Something went wrong. Please try again." text.
**Known Fragility:** `[NOTABLE]` The received `error` object (including its message and `digest`) is discarded — never logged, never surfaced to the user, making production debugging of which specific error occurred harder without external log correlation via `digest`. Markup/classes/testids are deliberately duplicated in `InlineLoadError` (M-081) per that module's own comment ("reusing the exact same markup...so the two read as one pattern") — changing this component's DOM structure without updating M-081 in lockstep would create a visual/testing inconsistency between the two.
**Change Impact:** Governs the fallback UI for every unhandled render error across Home, Upload, Exceptions, Exceptions Detail, and Document Detail pages. Because M-073 and M-075 deliberately `throw new Error(...)` on not-found conditions (rather than a dedicated 404 page), this component doubles as their "not found" UI — changing its wording changes what users see for both real errors and not-found cases alike.
**Callers:** Framework-invoked automatically by Next.js for uncaught errors within the `(app)` route group; not directly imported by other modules.
**Calls:** None (calls `reset()`, a function passed in by the framework, not another module).
**Integration Points Used:** None (fetches internal API routes only) — N/A, no fetch.
