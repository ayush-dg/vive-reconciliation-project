**Module:** IconSprite
**ID:** M-080
**Layer:** component
**Primary Responsibility:** Renders a hidden, zero-size SVG `<defs>` block containing all icon symbols used app-wide, so other components can reference them cheaply via `<use href="#i-name">`.

**Inputs (Props):** None.
**Outputs (Rendered UI + Side Effects):** Renders a single `<svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">` containing nine `<symbol>` definitions: `i-home`, `i-upload`, `i-alert`, `i-file`, `i-users`, `i-settings`, `i-check-circle`, `i-key`, `i-folder`. No side effects.
**State Consumed:** None.
**Public Interface:** `export default function IconSprite()`.
**Error Behaviour:** N/A — static markup only, cannot fail.
**Known Fragility:** `[NOTABLE]` Must be mounted before (or at least alongside, in the DOM) any component that references `<use href="#i-...">`, since SVG `<use>` resolves the referenced `#id` at render/paint time — it is currently mounted once at the true root (M-060, RootLayout), which covers every route including `/login`, so this is safe today. A future engineer moving `IconSprite` out of the root layout, or wrapping it in conditional rendering, would break every icon reference across Sidebar (M-082), UploadForm (M-070), LoginForm (M-063), etc. The symbol set is "trimmed to icons this build's six screens actually use" per its comment — an icon name referenced elsewhere (`<use href="#i-something-not-here">`) that isn't in this list will render nothing, with no error or warning.
**Change Impact:** Adding/removing/renaming a `<symbol id="...">` here directly affects every `<use href="#...">` reference across the codebase — M-063 (`#i-key`), M-070 (`#i-folder`, `#i-file`), M-082 (`#i-home`, `#i-upload`, `#i-alert`, `#i-settings`), and any other component using these icon ids (out of this session's scope to enumerate exhaustively).
**Callers:** M-060 (RootLayout) renders this.
**Calls:** None.
**Integration Points Used:** None (fetches internal API routes only) — N/A, no fetch.
