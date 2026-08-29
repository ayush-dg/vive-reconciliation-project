'use client';

// Shared inline error + Retry for a CLIENT-SIDE data refetch failure (search, pagination,
// or a post-action refresh) — distinct from error.tsx's SSR/render-time error boundary,
// but reusing the exact same markup/classes/testids so the two read as one pattern, not
// two similar-looking ones (Task 6.4's own point: no screen invents its own version of
// this). Used by Home, Exceptions, and Document Detail alike.
export default function InlineLoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="error-boundary" role="alert" data-testid="error-boundary">
      <p>Something went wrong. Please try again.</p>
      <button type="button" className="btn btn-secondary" onClick={onRetry} data-testid="error-retry">
        Retry
      </button>
    </div>
  );
}
