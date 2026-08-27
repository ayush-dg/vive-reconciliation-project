'use client';

import { useEffect, useState } from 'react';
import { toastStore, type Toast } from '@/lib/toastStore';

// Bottom-right position, per UI_SURFACE.md's Global Elements > Toast /
// Notification System. First real trigger: Task 2.1's upload confirmation.
export default function ToastProvider() {
  const [toasts, setToasts] = useState<Toast[]>(toastStore.getToasts());

  useEffect(() => toastStore.subscribe(setToasts), []);

  if (toasts.length === 0) return null;

  return (
    <div role="status" aria-live="polite" data-testid="toast-container" className="toast-container">
      {toasts.map((toast) => (
        <div key={toast.id} data-testid={`toast-${toast.kind}`} role="alert" className={`toast toast-${toast.kind}`}>
          {toast.message}
          <button type="button" onClick={() => toastStore.dismiss(toast.id)} aria-label="Dismiss">
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

export function useToast() {
  return { showSuccess: (message: string) => toastStore.add('success', message), showError: (message: string) => toastStore.add('error', message) };
}
