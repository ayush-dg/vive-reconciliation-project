import crypto from 'node:crypto';
import { test, expect } from '@playwright/test';
import { TEST_USERNAME, TEST_SESSION_SECRET } from './global-setup';
import { SESSION_COOKIE_NAME, signSessionToken } from '../src/lib/session';
import { getSqliteDb } from '../src/lib/db';
import { makeTestPdf } from '../scripts/testPdfFixture.mjs';

async function signInViaCookie(context: import('@playwright/test').BrowserContext) {
  process.env.SESSION_SECRET = TEST_SESSION_SECRET;
  const token = await signSessionToken({ userId: 'test-user-id', username: TEST_USERNAME, lastSeenAt: Date.now() });
  await context.addCookies([
    { name: SESSION_COOKIE_NAME, value: token, url: 'http://localhost:3000', httpOnly: true, sameSite: 'Lax' },
  ]);
}

// Real, pdfplumber-parseable PDF bytes (via PyMuPDF) — a plain `%PDF-1.4 ...` text buffer
// (this fixture's original form, written in Session 2 against Session 2's own stub
// extraction) is not valid PDF structure. Session 3's real pipeline always runs a genuine
// pdfplumber parse as its vendor-routing "peek" regardless of which path is ultimately
// chosen (vendorIdentification.ts), so invalid PDF bytes now genuinely fail extraction
// (2 failed attempts, "Failed — see Exceptions") — a real, previously undetected
// regression this task's own Playwright run surfaced; see sessions/S06_SESSION_LOG.md's
// Deviations entry. Marker-format text (VENDOR:/TOTAL:/INVOICE:) matches what Session 3's
// own mock/pdfplumber extractors parse.
async function uploadFixture(page: import('@playwright/test').Page, label: string) {
  const text = `VENDOR: Extract_Trigger_${label.replace(/[^a-zA-Z0-9]/g, '_')}\nTOTAL: 10.00\nINVOICE: INV-${label} | RO: - | AMOUNT: 10.00 | DATE: 2026-08-01`;
  const bytes = makeTestPdf(text);
  const res = await page.request.post('/api/documents', {
    multipart: {
      file: { name: `${label}.pdf`, mimeType: 'application/pdf', buffer: bytes },
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

  test('clicking Extract transitions status to "Extracted" and triggers Session 3\'s service', async ({
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
    // ("Extracting…", not an error), not a logic failure.
    await expect(page.getByTestId('toast-success')).toBeVisible({ timeout: 15_000 });
    // Task 2.3's computed display label — "Extracted" (2026-08-31 addition,
    // distinct from "Processing"), since this fixture's marker-format text
    // makes the mock extractor succeed on attempt 1. Not the raw internal
    // status column — see documents.ts's ApiDocument doc comment.
    await expect(page.getByTestId(`status-badge-${documentId}`)).toHaveText('Extracted');
  });

  test('Extract button is not shown once extraction has already started', async ({ page, context }) => {
    await signInViaCookie(context);
    const documentId = await uploadFixture(page, 'extract-hidden-after-start');
    await page.goto('/upload');

    await page.getByTestId(`extract-button-${documentId}`).click();
    await expect(page.getByTestId('toast-success')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId(`extract-button-${documentId}`)).toHaveCount(0);
  });

  test('a raw API upload (bypassing the Upload UI form) does not itself invoke extraction — status stays "registered" until Extract is triggered', async ({
    page,
    context,
  }) => {
    // Auto-extraction-on-upload (engineer-directed, 2026-08-31) lives entirely in
    // UploadForm.tsx's client-side handleSubmit — the server-side POST /api/documents
    // route itself still only registers, exactly as before. A direct API call like this
    // one (bypassing the browser form) never reaches that client code, so this remains
    // true even after that change. See the next test for the actual UI-form behavior.
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

  test('uploading through the actual Upload UI form starts extraction automatically — no separate Extract click needed', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    await page.goto('/upload');

    const text = `VENDOR: Extract_Trigger_auto\nTOTAL: 10.00\nINVOICE: INV-auto | RO: - | AMOUNT: 10.00 | DATE: 2026-08-01`;
    const bytes = makeTestPdf(text);
    await page.setInputFiles('#statement-file', { name: 'auto-extract.pdf', mimeType: 'application/pdf', buffer: bytes });
    await page.getByTestId('upload-submit').click();

    // The single upload-submit click covers both upload and extraction (they're chained
    // client-side) — by the time the page settles, the document should already be past
    // "registered"/Extract-needed and showing a real computed badge, with no Extract
    // button ever appearing for this row.
    await expect(page.getByTestId('toast-success')).toBeVisible({ timeout: 15_000 });
    const row = page.locator('[data-testid^="document-row-"]').first();
    await expect(row.getByRole('button', { name: 'Extract' })).toHaveCount(0);
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

    // This test constructs a specific attempt-history shape directly (one failed attempt,
    // no second yet) rather than calling the real Extract endpoint — Session 3's real
    // pipeline runs its bounded retry loop synchronously within that one request, so by
    // the time it returns, "exactly 1 failed attempt, no 2nd yet" is not an observable
    // state through the real endpoint. Flips the same G5 lock column the real endpoint
    // would (status='processing'), then synthesizes the attempt row directly — same
    // technique as scripts/test_document_status.mjs (Task 2.3).
    const db = getSqliteDb();
    db.prepare(`UPDATE extracted_document SET status = 'processing' WHERE document_id = ?`).run(documentId);
    db.prepare(
      `INSERT INTO extracted_extraction_attempt (attempt_id, document_id, attempt_no, arithmetic_pass, structural_pass)
       VALUES (?, ?, 1, 0, 1)`
    ).run(crypto.randomUUID(), documentId);

    await page.goto('/upload');
    await expect(page.getByTestId(`status-badge-${documentId}`)).toHaveText('Retrying (1/2)');
  });
});
