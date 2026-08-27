// Unit test for src/lib/toastStore.ts's framework-agnostic logic — no browser,
// no testing-library dependency. Run: npm run test:toast
import { createToastStore } from '../src/lib/toastStore.ts';

let failures = 0;
function check(label, condition) {
  if (condition) {
    console.log(`PASS: ${label}`);
  } else {
    console.error(`FAIL: ${label}`);
    failures++;
  }
}

// --- add() appends a toast and notifies subscribers ---
{
  const store = createToastStore();
  let lastNotified = null;
  store.subscribe((toasts) => (lastNotified = toasts));
  const id = store.add('success', 'Upload received', 0);
  check('add() returns an id', typeof id === 'string' && id.length > 0);
  check('add() appends to getToasts()', store.getToasts().some((t) => t.id === id));
  check('subscribers are notified on add()', lastNotified?.some((t) => t.id === id));
}

// --- dismiss() removes a toast and notifies subscribers ---
{
  const store = createToastStore();
  const id = store.add('error', 'Extraction failed', 0);
  let lastNotified = null;
  store.subscribe((toasts) => (lastNotified = toasts));
  store.dismiss(id);
  check('dismiss() removes from getToasts()', !store.getToasts().some((t) => t.id === id));
  check('subscribers are notified on dismiss()', !lastNotified.some((t) => t.id === id));
}

// --- dismiss() on an unknown id is a no-op (does not throw, does not notify) ---
{
  const store = createToastStore();
  let notifyCount = 0;
  store.subscribe(() => notifyCount++);
  store.dismiss('not-a-real-id');
  check('dismiss() on unknown id does not throw or notify', notifyCount === 0);
}

// --- auto-dismiss fires after the configured delay ---
{
  const store = createToastStore();
  const id = store.add('success', 'Auto-expiring', 50);
  check('toast present immediately after add()', store.getToasts().some((t) => t.id === id));
  await new Promise((resolve) => setTimeout(resolve, 150));
  check('toast auto-dismissed after its delay', !store.getToasts().some((t) => t.id === id));
}

// --- multiple toasts coexist independently ---
{
  const store = createToastStore();
  const id1 = store.add('success', 'First', 0);
  const id2 = store.add('error', 'Second', 0);
  check('multiple toasts coexist', store.getToasts().length === 2);
  store.dismiss(id1);
  check('dismissing one leaves the other', store.getToasts().length === 1 && store.getToasts()[0].id === id2);
}

// --- unsubscribe stops further notifications ---
{
  const store = createToastStore();
  let notifyCount = 0;
  const unsubscribe = store.subscribe(() => notifyCount++);
  store.add('success', 'One', 0);
  unsubscribe();
  store.add('success', 'Two', 0);
  check('unsubscribe() stops further notifications', notifyCount === 1);
}

if (failures > 0) {
  console.error(`\n${failures} test case(s) FAILED.`);
  process.exit(1);
}
console.log('\nAll toastStore test cases PASS.');
