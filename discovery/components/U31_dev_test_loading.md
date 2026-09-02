**Module:** Dev Test Loading Page
**ID:** M-078
**Layer:** page
**Primary Responsibility:** Introduces a deliberate 1-second artificial delay before rendering, solely so an automated UI test can observe the app-level loading spinner (M-065) actually mount.

**Inputs (Props):** None.
**Outputs (Rendered UI + Side Effects):** `async` server component; `await`s a `setTimeout`-based `Promise` for 1000ms, then renders `<p data-testid="dev-test-loading-content">Loaded.</p>`. No other side effects.
**State Consumed:** None.
**Public Interface:** `export default async function TestLoadingPage()`.
**Error Behaviour:** No error handling — nothing here can realistically fail besides the timer itself.
**Known Fragility:** Per its own comment, "nothing else in this session has a slow enough data fetch to exercise [loading.tsx] naturally yet" — meaning M-065's loading UI is currently *only* exercised by this artificial delay in real testing; if this page were ever removed without a genuinely slow real data path replacing it, `loading.tsx`'s behavior would go unverified by tests.
**Known/navigation note:** Not linked from the Sidebar (M-082) or any in-app `<Link>` — reachable only by direct URL (`/dev-test-loading`); exists solely for `ui_tests/global-elements.spec.ts`.
**Change Impact:** Isolated — only affects the automated test that navigates here directly. Changing the delay duration could make the test flaky if it's tuned to a specific timing assumption (`NOT DETERMINABLE FROM SOURCE` what the test itself asserts on timing).
**Callers:** None in-app (test-only, navigated to directly by an external test script).
**Calls:** None.
**Integration Points Used:** None (fetches internal API routes only) — N/A, no fetch.
