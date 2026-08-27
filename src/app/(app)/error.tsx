'use client';

// Global error boundary (UI_SURFACE.md Global Elements): inline message + Retry
// action, no full-page redirect (resolved default). Next.js error.tsx
// convention — catches errors thrown during rendering within this route group.
export default function AppError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="error-boundary" role="alert" data-testid="error-boundary">
      <p>Something went wrong. Please try again.</p>
      <button type="button" className="btn btn-secondary" onClick={reset} data-testid="error-retry">
        Retry
      </button>
    </div>
  );
}
