**Module:** InlineLoadError
**ID:** M-081
**Layer:** component
**Primary Responsibility:** Shared, presentational inline "Something went wrong" + Retry control for client-side data-refetch failures (as opposed to render-time errors, which use the `error.tsx` boundary instead).

**Inputs (Props):** `{ onRetry: () => void }`.
**Outputs (Rendered UI + Side Effects):** Renders `<div className="error-boundary" role="alert" data-testid="error-boundary">` with a static message and a "Retry" button whose `onClick` calls the passed-in `onRetry`. No internal side effects — entirely delegates the retry behavior to the caller.
**State Consumed:** None.
**Public Interface:** `export default function InlineLoadError({ onRetry }: { onRetry: () => void })`; marked `'use client'`.
**Error Behaviour:** N/A — this component *is* the error-display UI, not something that itself errors.
**Known Fragility:** `[NOTABLE]` Deliberately duplicates the exact markup, CSS classes, and `data-testid` values of `(app)/error.tsx` (M-066) — per its own comment, "reusing the exact same markup/classes/testids so the two read as one pattern, not two similar-looking ones." This means the two components must be kept in sync manually; there is no shared sub-component or extracted markup enforcing the duplication, so a styling/copy change made to one and not the other would create a visible inconsistency between the render-time error boundary and the refetch-failure UI. Also means both M-066 and every usage of M-081 share the identical `data-testid="error-boundary"` — a UI test cannot distinguish "render-time error boundary fired" from "an inline refetch failed" by testid alone; it must rely on which page/context it's checking.
**Change Impact:** Used by M-068 (Home), M-072 (Exceptions vendor list), M-074 (Exception vendor detail), and M-076 (Document Detail) — a change to this component's markup or behavior affects all four screens' refetch-failure UX simultaneously.
**Callers:** M-068, M-072, M-074, M-076 (all render this conditionally on their own `loadError`/`listLoadError` state).
**Calls:** None (calls the `onRetry` prop supplied by the caller).
**Integration Points Used:** None (fetches internal API routes only) — N/A, no fetch of its own.
