**Module:** Dev Test Error Page
**ID:** M-077
**Layer:** page
**Primary Responsibility:** Deterministically throws an error on render, solely to give an automated UI test a reliable way to trigger the global error boundary (M-066).

**Inputs (Props):** None.
**Outputs (Rendered UI + Side Effects):** Never renders anything — unconditionally throws `Error('Simulated error for ui_tests/global-elements.spec.ts')`. Return type annotated `never`.
**State Consumed:** None.
**Public Interface:** `export default function TestErrorPage(): never`.
**Error Behaviour:** This module *is* an error trigger — every render throws, caught by `(app)/error.tsx` (M-066).
**Known Fragility:** Per its own comment, the folder is deliberately named `dev-test-error` (no leading underscore) rather than `__test-error`, because Next.js treats `_folder` segments as private/non-routable — an engineer "cleaning up" this naming convention without knowing that history could accidentally make the route unreachable again (404), silently breaking the test that depends on it.
**Known/navigation note:** Not linked from the Sidebar (M-082) or any in-app `<Link>` — reachable only by direct URL (`/dev-test-error`); exists solely for `ui_tests/global-elements.spec.ts`.
**Change Impact:** Isolated — only affects the automated test that navigates here directly. No other module renders or links to it.
**Callers:** None in-app (test-only, navigated to directly by an external test script).
**Calls:** None.
**Integration Points Used:** None (fetches internal API routes only) — N/A, no fetch.
