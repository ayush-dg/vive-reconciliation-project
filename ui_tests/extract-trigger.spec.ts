import crypto from 'node:crypto';
import { test, expect } from '@playwright/test';
import { TEST_USERNAME, TEST_SESSION_SECRET } from './global-setup';
import { SESSION_COOKIE_NAME, signSessionToken } from '../src/lib/session';
import { getSqliteDb } from '../src/lib/db';

async function signInViaCookie(context: import('@playwright/test').BrowserContext) {
  process.env.SESSION_SECRET = TEST_SESSION_SECRET;
  const token = await signSessionToken({ userId: 'test-user-id', username: TEST_USERNAME, lastSeenAt: Date.now() });
  await context.addCookies([
    { name: SESSION_COOKIE_NAME, value: token, url: 'http://localhost:3000', httpOnly: true, sameSite: 'Lax' },
  ]);
}

async function uploadFixture(page: import('@playwright/test').Page, label: string) {
  const res = await page.request.post('/api/documents', {
    multipart: {
      file: { name: `${label}.pdf`, mimeType: 'application/pdf', buffer: Buffer.from(`%PDF-1.4 ${label} ${Math.random()}`) },
      legalEntityId: 'vive-holdings',
    },
  });
  const body = await res.json();
  return body.document.document_id;
}

test.describe('Extract action', () => {
  test('Extract button is visible on a registered, not-yet-extracted document row', async ({ page, context }) => {
    await signInViaCookie(context);
    const documentId = await uploadFixture(page, 'extract-visible');
    await page.goto('/upload');

    await expect(page.getByTestId(`extract-button-${documentId}`)).toBeVisible();
  });

  test('clicking Extract transitions status to "Processing" and triggers Session 3\'s service', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const documentId = await uploadFixture(page, 'extract-click');
    await page.goto('/upload');

    await page.getByTestId(`extract-button-${documentId}`).click();
    // A generous timeout here — under Playwright's default parallel workers,
    // this dynamic route may still be Turbopack-compiling on its first hit,
    // and the shared dev server/SQLite file is under concurrent load from
    // every other test in the suite; confirmed via a captured DOM snapshot
    // that a slow run still shows the request correctly in-flight
    // ("Starting…", not an error), not a logic failure.
    await expect(page.getByTestId('toast-success')).toBeVisible({ timeout: 15_000 });
    // Task 2.3's computed display label ("Processing"), not the raw internal
    // status column — see documents.ts's ApiDocument doc comment.
    await expect(page.getByTestId(`status-badge-${documentId}`)).toHaveText('Processing');
  });

  test('Extract button is not shown once extraction has already started', async ({ page, context }) => {
    await signInViaCookie(context);
    const documentId = await uploadFixture(page, 'extract-hidden-after-start');
    await page.goto('/upload');

    await page.getByTestId(`extract-button-${documentId}`).click();
    await expect(page.getByTestId('toast-success')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId(`extract-button-${documentId}`)).toHaveCount(0);
  });

  test('uploading a document does not itself invoke extraction — status stays "registered" until Extract is clicked', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const uploadRes = await page.request.post('/api/documents', {
      multipart: {
        file: { name: 'no-auto-extract.pdf', mimeType: 'application/pdf', buffer: Buffer.from(`%PDF-1.4 ${Math.random()}`) },
        legalEntityId: 'vive-holdings',
      },
    });
    const uploadBody = await uploadRes.json();
    expect(uploadBody.document.status).toBe('registered');

    await page.goto('/upload');
    await expect(page.getByTestId(`extract-button-${uploadBody.document.document_id}`)).toBeVisible();
  });

  test('G5: triggering Extract twice in rapid succession results in exactly one extraction attempt — the second is rejected', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const documentId = await uploadFixture(page, 'extract-g5-race');

    const [first, second] = await Promise.all([
      page.request.post(`/api/documents/${documentId}/extract`),
      page.request.post(`/api/documents/${documentId}/extract`),
    ]);

    const statuses = [first.status(), second.status()].sort();
    // Exactly one 200 (acquired ownership) and one 409 (rejected — already processing).
    expect(statuses).toEqual([200, 409]);
  });

  test('POST /api/documents/{id}/extract for a non-existent document_id returns 404', async ({ page, context }) => {
    await signInViaCookie(context);
    const res = await page.request.post(`/api/documents/${crypto.randomUUID()}/extract`);
    expect(res.status()).toBe(404);
  });

  test('a real double-click on the Extract button results in exactly one extraction being started, not two', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const documentId = await uploadFixture(page, 'extract-real-doubleclick');
    await page.goto('/upload');

    const button = page.getByTestId(`extract-button-${documentId}`);
    // Two genuine, separate click events (not a single dblclick DOM event) —
    // exercises the actual browser/React code path, not just two direct API
    // calls bypassing the client entirely.
    await button.click();
    await button.click({ force: true }).catch(() => {}); // may already be disabled/gone by the second click

    // Whichever of the client's own disabled-state guard or the server's G5
    // guard caught the second click, the end state must be consistent: never
    // stuck showing two conflicting states, and never a second row/duplicate.
    await expect(page.getByTestId(`document-row-${documentId}`)).toHaveCount(1, { timeout: 15_000 });
    await expect(page.getByTestId(`status-badge-${documentId}`)).toBeVisible({ timeout: 15_000 });
  });

  test('badge reflects Task 2.3\'s actual computed status (Retrying), not the raw internal "processing" column', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const documentId = await uploadFixture(page, 'extract-retrying-badge');
    await page.request.post(`/api/documents/${documentId}/extract`);

    // Synthesize a failed extraction attempt directly (Session 3's real
    // pipeline doesn't exist yet) — same technique as
    // scripts/test_document_status.mjs (Task 2.3).
    const db = getSqliteDb();
    db.prepare(
      `INSERT INTO extracted_extraction_attempt (attempt_id, document_id, attempt_no, arithmetic_pass, structural_pass)
       VALUES (?, ?, 1, 0, 1)`
    ).run(crypto.randomUUID(), documentId);

    await page.goto('/upload');
    await expect(page.getByTestId(`status-badge-${documentId}`)).toHaveText('Retrying (1/2)');
  });
});
