**Module:** App Loading (Next.js loading.tsx)
**ID:** M-065
**Layer:** layout
**Primary Responsibility:** Global loading-state UI (spinner) shown automatically by Next.js's Suspense convention during initial load and route transitions within the `(app)` route group.

**Inputs (Props):** None (Next.js `loading.tsx` convention takes no props).
**Outputs (Rendered UI + Side Effects):** Renders a static `<div className="app-loading" data-testid="app-loading-spinner">` with a `<span className="spinner">` and "Loading…" text. No side effects.
**State Consumed:** None.
**Public Interface:** `export default function Loading()`.
**Error Behaviour:** N/A — purely presentational, no data fetching, cannot itself error.
**Known Fragility:** Per its own comment, this is deliberately a simple spinner with "no skeleton loaders (resolved default)" — a future engineer adding skeleton UI elsewhere would be introducing an inconsistency unless they also update this. Exercised deliberately by the test-only M-078 (`dev-test-loading/page.tsx`) via an artificial 1s delay, since no real data fetch in this build is slow enough to trigger it naturally (per that module's comment).
**Change Impact:** Affects the loading experience for every route under `(app)` during Suspense-triggered transitions; low blast radius since it's presentation-only.
**Callers:** Framework-invoked automatically by Next.js's App Router (Suspense boundary) for the `(app)` route group; not directly imported by other modules, though M-078 exists specifically to exercise it.
**Calls:** None.
**Integration Points Used:** None (fetches internal API routes only) — N/A, no fetch at all.
