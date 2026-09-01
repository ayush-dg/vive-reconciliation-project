import fs from 'node:fs';
import crypto from 'node:crypto';
import { test, expect } from '@playwright/test';
import { TEST_USERNAME, TEST_SESSION_SECRET } from './global-setup';
import { SESSION_COOKIE_NAME, signSessionToken } from '../src/lib/session';

async function signInViaCookie(context: import('@playwright/test').BrowserContext) {
  process.env.SESSION_SECRET = TEST_SESSION_SECRET;
  const token = await signSessionToken({ userId: 'test-user-id', username: TEST_USERNAME, lastSeenAt: Date.now() });
  await context.addCookies([
    { name: SESSION_COOKIE_NAME, value: token, url: 'http://localhost:3000', httpOnly: true, sameSite: 'Lax' },
  ]);
}

// Task 6.4 — confirms Home, Exceptions, and Exception Detail use the SAME global
// loading/error patterns (Session 1, Task 1.4) rather than each screen inventing its own.
//
// Structural check (all three routes): Next.js's loading.tsx/error.tsx are file-based —
// a route only gets its own if a file is deliberately added at that path. Confirming no
// such override file exists is a direct, reliable proof of "not screen-specific", unlike
// trying to force a real network-latency race in a local SQLite dev environment (data
// fetches here are near-instant; artificially slowing production code just to make a
// timing-dependent test pass would be worse than not testing it at all — see Known
// Untested Scenarios in this task's Verification Record entry).
//
// Behavioral check (Document Detail + Exception Detail): both have a natural, reliable
// error trigger (an unknown id throws, per each page.tsx's own doc comment) — confirms the
// identical error-boundary/error-retry testids render on both, proving they share one
// error component rather than two similar-looking ones. Home/Exceptions have no such
// natural trigger (no :id param) — their sharing is covered by the structural check above.
test.describe('Loading/Error consistency (Home, Exceptions, Exception Detail)', () => {
  test('no screen under this session defines its own loading.tsx or error.tsx', () => {
    const routeDirs = [
      'src/app/(app)/home',
      'src/app/(app)/exceptions',
      'src/app/(app)/exceptions/[vendorSlug]',
      'src/app/(app)/documents/[id]',
    ];
    for (const dir of routeDirs) {
      expect(fs.existsSync(`${dir}/loading.tsx`), `${dir}/loading.tsx should not exist`).toBe(false);
      expect(fs.existsSync(`${dir}/error.tsx`), `${dir}/error.tsx should not exist`).toBe(false);
    }
    // The one shared implementation this build actually uses.
    expect(fs.existsSync('src/app/(app)/loading.tsx')).toBe(true);
    expect(fs.existsSync('src/app/(app)/error.tsx')).toBe(true);
  });

  test('Document Detail and Exception Detail render the identical global error boundary on a not-found id', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);

    await page.goto(`/documents/${crypto.randomUUID()}`);
    await expect(page.getByTestId('error-boundary')).toBeVisible();
    await expect(page.getByTestId('error-retry')).toBeVisible();
    const documentErrorText = await page.getByTestId('error-boundary').textContent();

    await page.goto(`/exceptions/${crypto.randomUUID()}`);
    await expect(page.getByTestId('error-boundary')).toBeVisible();
    await expect(page.getByTestId('error-retry')).toBeVisible();
    const exceptionErrorText = await page.getByTestId('error-boundary').textContent();

    // Same component, same copy — not two screens each rendering their own similar-looking
    // error UI.
    expect(documentErrorText).toBe(exceptionErrorText);
  });

  test('Home and Exceptions render without error under normal conditions (no screen-specific error UI to diverge)', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    await page.goto('/home');
    await expect(page.getByTestId('error-boundary')).toHaveCount(0);
    await page.goto('/exceptions');
    await expect(page.getByTestId('error-boundary')).toHaveCount(0);
  });

  // Challenge-review addition: the SSR/not-found error path above only covers Document
  // Detail and Exception Detail (the two screens with a natural throw trigger). The
  // CLIENT-SIDE refetch failure path (search/pagination on Exceptions, post-action
  // refresh on Home/Document Detail) is a SEPARATE code path this test previously never
  // touched — and it's exactly where a real inconsistency was found: Task 6.2's own fix
  // for Exceptions initially hand-duplicated error.tsx's markup with different testids,
  // while Home/Document Detail had no error handling there at all. All three now share
  // the same InlineLoadError component (src/components/InlineLoadError.tsx) — confirmed
  // here directly, across all three screens in one test, rather than left to each
  // screen's own spec file to prove in isolation.
  test('Home, Exceptions, and Document Detail render the IDENTICAL client-side refetch error on a failed data reload', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);

    async function uploadFixture(text: string) {
      const res = await page.request.post('/api/documents', {
        multipart: {
          file: { name: `consistency-test-${crypto.randomUUID()}.pdf`, mimeType: 'application/pdf', buffer: Buffer.from(text) },
          legalEntityId: 'vive-holdings',
        },
      });
      const body = await res.json();
      return body.document.document_id as string;
    }

    // Home: a failed /api/documents refetch after a real Extract click.
    const homeDocId = await uploadFixture('%PDF-1.4 consistency-home');
    await page.goto('/home');
    await page.route('**/api/documents', (route) =>
      route.request().method() === 'GET'
        ? route.fulfill({ status: 500, body: '{}' })
        : route.continue()
    );
    await page.getByTestId(`home-extract-button-${homeDocId}`).click();
    await expect(page.getByTestId('error-boundary')).toBeVisible();
    const homeErrorText = await page.getByTestId('error-boundary').textContent();
    await page.unroute('**/api/documents');

    // Exceptions: a failed /api/exceptions refetch after clicking Refresh.
    await page.goto('/exceptions');
    await page.route('**/api/exceptions', (route) => route.fulfill({ status: 500, body: '{}' }));
    await page.getByTestId('exceptions-vendor-refresh').click();
    await expect(page.getByTestId('error-boundary')).toBeVisible();
    const exceptionsErrorText = await page.getByTestId('error-boundary').textContent();
    await page.unroute('**/api/exceptions');

    // Document Detail: a failed /api/documents/:id/detail refetch after a real Extract click.
    const docDetailId = await uploadFixture('%PDF-1.4 consistency-doc-detail');
    await page.goto(`/documents/${docDetailId}`);
    await page.route(`**/api/documents/${docDetailId}/detail`, (route) => route.fulfill({ status: 500, body: '{}' }));
    await page.getByTestId('document-detail-extract-button').click();
    await expect(page.getByTestId('error-boundary')).toBeVisible();
    const documentDetailErrorText = await page.getByTestId('error-boundary').textContent();

    // All three: the same component, same copy — not three (or two-plus-none) different
    // implementations of "an error happened, try again".
    expect(homeErrorText).toBe(exceptionsErrorText);
    expect(exceptionsErrorText).toBe(documentDetailErrorText);
  });
});
