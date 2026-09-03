**Module:** vendorDisplay.ts
**ID:** M-010
**Layer:** infra
**Primary Responsibility:** Pure, zero-import helper that humanizes a `vendor_slug` into a display label (e.g. `"fred_beans_parts_inc"` -> `"Fred Beans Parts Inc"`), kept dependency-free so client components can use it without pulling in server-only DB packages.

**Inputs:** `vendorSlug: string` — no validation performed.

**Outputs:** Formatted display `string`. No side effects, no I/O.

**Public Interface:**
- `humanizeVendorSlug(vendorSlug: string): string`

**Error Behaviour:** Never throws — implemented entirely with `String.prototype` methods (`split`/`filter`/`map`/`join`). An empty, `undefined`-like, or malformed slug just produces an empty or oddly-formatted string rather than an error.

**Known Fragility:**
- **[NOTABLE architectural constraint]** The module's entire reason for existing is being importable from `'use client'` components without dragging in `db.ts`'s Node-only packages (`better-sqlite3`/`mssql`, which fail to bundle for the browser with a `"Module not found: Can't resolve 'tls'"` error, per the header comment). Any future edit that adds even one import to this file — e.g. a shared string-utils helper — risks silently reintroducing that build failure for every client component consuming it. This constraint is documentation-only; nothing enforces it structurally (no lint rule observed).
- Assumes `vendor_slug` is the *only* source of a display name (`extracted_vendor_registry` never carries a separate display-name column, per the comment) — if a real display-name field is ever added upstream, this humanization becomes a fallback/legacy path with nothing here signaling that dependency has changed.
- Capitalization is naive (`char.toUpperCase() + rest`) — does not correctly handle acronyms or mixed-case slugs (e.g. a slug embedding "ksi" renders as `"Ksi"`, not `"KSI"`), a cosmetic but potentially vendor-name-misrepresenting issue.

**Change Impact:** Callers M-072 and M-074. Purely presentational — changes affect only how vendor names render in the UI, not data correctness. A broken zero-import constraint, however, would be a client-bundle build failure for whichever client components import this module.

**Callers:** M-072, M-074
**Calls:** None
**Integration Points Used:** None
