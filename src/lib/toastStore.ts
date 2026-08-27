/**
 * Framework-agnostic toast store (Task 1.4). Deliberately not React-specific —
 * the logic (add/dismiss/auto-expire/subscribe) is unit-testable directly via
 * scripts/test_toast_store.mjs without a browser or a testing-library
 * dependency; src/components/ToastProvider.tsx is a thin React subscriber.
 */

export type ToastKind = 'success' | 'error';

export type Toast = {
  id: string;
  kind: ToastKind;
  message: string;
};

type Listener = (toasts: Toast[]) => void;

const DEFAULT_AUTO_DISMISS_MS = 5000;

export function createToastStore() {
  let toasts: Toast[] = [];
  const listeners = new Set<Listener>();
  const timers = new Map<string, ReturnType<typeof setTimeout>>();

  function notify() {
    for (const listener of listeners) listener(toasts);
  }

  function dismiss(id: string) {
    const timer = timers.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.delete(id);
    }
    if (!toasts.some((t) => t.id === id)) return;
    toasts = toasts.filter((t) => t.id !== id);
    notify();
  }

  function add(kind: ToastKind, message: string, autoDismissMs = DEFAULT_AUTO_DISMISS_MS): string {
    const id = crypto.randomUUID();
    toasts = [...toasts, { id, kind, message }];
    notify();
    if (autoDismissMs > 0) {
      timers.set(
        id,
        setTimeout(() => dismiss(id), autoDismissMs)
      );
    }
    return id;
  }

  function subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  function getToasts(): Toast[] {
    return toasts;
  }

  return { add, dismiss, subscribe, getToasts };
}

// App-wide singleton — one toast stream shared across the (app) layout.
export const toastStore = createToastStore();
