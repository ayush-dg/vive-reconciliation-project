**Module:** toastStore.ts
**ID:** M-009
**Layer:** infra
**Primary Responsibility:** Framework-agnostic pub/sub store for toast notifications (add/dismiss/auto-expire/subscribe), unit-testable without a browser, with an app-wide singleton instance for the shared toast stream.

**Inputs:**
- `kind: ToastKind ('success' | 'error')`, `message: string`, `autoDismissMs?: number` (default `5000`) — `add()`.
- `id: string` — `dismiss()`.
- `listener: (toasts: Toast[]) => void` — `subscribe()`.

**Outputs:** Mutates an internal `toasts` array and `timers` map held in each store instance's closure; synchronously calls every subscribed listener with the full current toast list on every `add`/`dismiss`. No I/O outside memory/timers.

**Public Interface:**
- `type ToastKind = 'success' | 'error'`
- `type Toast = { id: string; kind: ToastKind; message: string }`
- `createToastStore(): { add(kind: ToastKind, message: string, autoDismissMs?: number): string; dismiss(id: string): void; subscribe(listener: (toasts: Toast[]) => void): () => void; getToasts(): Toast[] }`
- `toastStore: ReturnType<typeof createToastStore>` — exported app-wide singleton instance

**Error Behaviour:** No try/catch anywhere; every operation is synchronous array/Set/Map mutation or `setTimeout` scheduling — nothing here is expected to throw under normal use. `crypto.randomUUID()` in `add()` is unguarded (could theoretically throw in a non-secure context, not handled).

**Known Fragility:**
- The exported `toastStore` is a true module-level singleton — every importer across the entire app shares the same instance and state. This module itself does nothing to prevent server-side import/mutation; the client-only discipline is enforced purely by convention in the consuming component (`ToastProvider.tsx`, not this file). If ever imported and mutated server-side, state would leak across requests/users since Node module instances are process-wide.
- `timers` (pending `setTimeout` handles) have no bulk-cleanup path — there's no `destroy()`/`clear()`; in practice this is low-impact since a fired timer with no listeners just calls `notify()` harmlessly, but it's an unbounded-until-fired resource with no explicit lifecycle management.
- `getToasts()` returns the live internal array reference, not a defensive copy — a caller that mutates the returned array directly would corrupt internal state with no protection (no `Object.freeze`, no copy).

**Change Impact:** Sole caller M-083 (the React toast-provider layer). The store's API is small and stable, so changes here mostly affect UI-visible toast timing/ordering rather than data-layer correctness.

**Callers:** M-083
**Calls:** None
**Integration Points Used:** None
