'use client';

// Test-only trigger for the Toast notification system (Task 1.4's CC prompt:
// "Toast notifications: bottom-right position, used for success confirmations
// and error alerts"). No real feature calls showSuccess/showError yet
// (Session 2's Upload confirmation is the first real trigger) — this page
// exists solely so ui_tests/global-elements.spec.ts can exercise ToastProvider
// end-to-end rather than only its underlying store logic. Not linked from the
// sidebar or any real navigation.
import { useToast } from '@/components/ToastProvider';

export default function TestToastPage() {
  const { showSuccess, showError } = useToast();
  return (
    <div>
      <button type="button" onClick={() => showSuccess('Simulated success toast')} data-testid="trigger-success-toast">
        Trigger success toast
      </button>
      <button type="button" onClick={() => showError('Simulated error toast')} data-testid="trigger-error-toast">
        Trigger error toast
      </button>
    </div>
  );
}
