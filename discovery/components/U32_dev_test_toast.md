**Module:** Dev Test Toast Page
**ID:** M-079
**Layer:** page
**Primary Responsibility:** Provides two buttons that trigger a success or error toast on demand, solely so an automated UI test can exercise the toast notification system end-to-end.

**Inputs (Props):** None.
**Outputs (Rendered UI + Side Effects):** Renders two buttons: "Trigger success toast" (`onClick` calls `showSuccess('Simulated success toast')`) and "Trigger error toast" (`onClick` calls `showError('Simulated error toast')`). Side effect: each click adds a toast to the shared `toastStore` (M-009, via M-083), visible wherever `ToastProvider` (M-083) is mounted (i.e., the `(app)` layout, M-064).
**State Consumed:** Reads `useToast()` (M-083) at lines 13, 17, 19.
**Public Interface:** `export default function TestToastPage()`; marked `'use client'`.
**Error Behaviour:** N/A — no fetches, nothing to fail.
**Known Fragility:** Per its own comment, "no real feature calls showSuccess/showError yet" at the time this test page was created (Session 2's Upload confirmation, M-070, was noted as "the first real trigger") — this history is now stale since M-068, M-070, and M-076 all call `useToast()` for real; the test page's comment overstates its uniqueness as the current sole caller, though it remains a valid deterministic simulator.
**Known/navigation note:** Not linked from the Sidebar (M-082) or any in-app `<Link>` — reachable only by direct URL (`/dev-test-toast`); exists solely for `ui_tests/global-elements.spec.ts`.
**Change Impact:** Isolated — only affects the automated test that navigates here directly. Depends entirely on `useToast`/`ToastProvider` (M-083) and, transitively, `toastStore` (M-009) — any breaking change to that hook's signature breaks this page too, alongside every real caller (M-068, M-070, M-076).
**Callers:** None in-app (test-only, navigated to directly by an external test script).
**Calls:** M-083 (useToast, lines 13, 17, 19).
**Integration Points Used:** None (fetches internal API routes only) — N/A, no fetch.
