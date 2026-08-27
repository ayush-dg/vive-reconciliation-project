// Test-only trigger for the Global Error Boundary (Task 1.4's test case:
// "triggering a simulated API error shows an inline message with a Retry
// button"). Not linked from the sidebar or any real navigation — exists solely
// so ui_tests/global-elements.spec.ts can deterministically exercise error.tsx.
// Named without a leading underscore deliberately — Next.js treats `_folder`
// segments as private/non-routable, which is exactly what routed to a 404
// when this page was first placed under `__test-error/`.
export default function TestErrorPage(): never {
  throw new Error('Simulated error for ui_tests/global-elements.spec.ts');
}
