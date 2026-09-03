**Module:** Root Layout
**ID:** M-060
**Layer:** layout
**Primary Responsibility:** Establishes the HTML document shell (fonts, metadata, global CSS) shared by every route in the app, including `/login` and the authenticated `(app)` group.

**Inputs (Props):** `{ children: React.ReactNode }` (implicit Next.js layout prop; not destructured with a type annotation in source, inferred).
**Outputs (Rendered UI + Side Effects):** Renders `<html>`/`<body>` with three self-hosted Google Fonts (Barlow Semi Condensed, Inter, IBM Plex Mono) applied as CSS variables on `<html className>`; renders `<IconSprite />` (M-080) once near the root, then `{children}`. Sets static `metadata` (title: "VIVE Statement Reconciliation", description). No side effects beyond font loading (self-hosted via `next/font`, no runtime external request per source comment).
**State Consumed:** None.
**Public Interface:** `export default function RootLayout({ children }: { children: React.ReactNode })`.
**Error Behaviour:** None handled here — this is the outermost layout; an error thrown during its own render would surface to Next.js's default (unhandled) error page since there is no `app/error.tsx` at this level, only inside `(app)/error.tsx` (M-066), which does not cover `/login` or this root layout itself. `NOT DETERMINABLE FROM SOURCE` whether a global-level error.tsx exists outside `(app)` — none was found in the file listing.
**Known Fragility:** Font `variable` names (`--font-display`, `--font-body`, `--font-mono`) are load-bearing for `globals.css`; renaming them here without updating the CSS breaks all typography app-wide. `IconSprite` must render before any component that references `<use href="#i-...">` — since it's mounted here at the root, this is currently safe, but moving it later in the tree or conditionally would break every icon usage.
**Change Impact:** Changing fonts, metadata, or removing `IconSprite` affects every page in the app (both `/login` and all `(app)` routes) since this is the single root layout.
**Callers:** Implicit — Next.js App Router mounts this automatically for all routes; not explicitly imported/rendered by any other module in scope.
**Calls:** None (no fetch, no lib calls).
**Renders:** M-080 (IconSprite) + `{children}`.
**Integration Points Used:** None (fetches internal API routes only) — N/A, this module makes no fetches at all.
