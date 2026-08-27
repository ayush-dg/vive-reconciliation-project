// App-level loading (UI_SURFACE.md Global Elements): simple spinner, no
// skeleton loaders (resolved default). Applies to initial load + route
// transitions within this route group, per Next's loading.tsx convention.
export default function Loading() {
  return <div data-testid="app-loading-spinner">Loading…</div>;
}
