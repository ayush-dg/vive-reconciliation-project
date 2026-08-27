// Test-only trigger for the app-level Loading state (loading.tsx). A deliberate
// artificial delay so Next.js's Suspense boundary actually mounts loading.tsx
// long enough for ui_tests/global-elements.spec.ts to observe it — nothing else
// in this session has a slow enough data fetch to exercise it naturally yet.
// Not linked from the sidebar or any real navigation.
export default async function TestLoadingPage() {
  await new Promise((resolve) => setTimeout(resolve, 1000));
  return <p data-testid="dev-test-loading-content">Loaded.</p>;
}
