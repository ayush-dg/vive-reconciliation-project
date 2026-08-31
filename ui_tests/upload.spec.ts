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

function samplePdf(label: string) {
  return {
    name: `${label}.pdf`,
    mimeType: 'application/pdf',
    buffer: Buffer.from(`%PDF-1.4 test fixture — ${label} — ${Math.random()}`),
  };
}

test.describe('Upload', () => {
  test('selecting a file and legal entity, then submitting, shows a confirmation toast and stays on /upload — no vendor field', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    await page.goto('/upload');

    // No vendor field anywhere on this screen (ARCHITECTURE.md D-L amendment).
    await expect(page.getByLabel(/vendor/i)).toHaveCount(0);

    await page.setInputFiles('#statement-file', samplePdf('fred-beans'));
    await page.getByTestId('upload-submit').click();

    await expect(page.getByTestId('toast-success')).toBeVisible();
    expect(new URL(page.url()).pathname).toBe('/upload');
  });

  // Real complaint fixed 2026-08-31: the Upload button previously stayed disabled for the
  // ENTIRE upload+auto-extraction chain (submitting only flipped false after extraction
  // finished too), so a second PDF couldn't be uploaded until the first one's extraction
  // completed — a real problem once extraction takes genuine multi-second time with live
  // Claude. Delays the first document's extraction call to prove the button re-enables
  // (and a second upload actually succeeds) well before that extraction resolves.
  test('a second PDF can be uploaded while the first one is still extracting', async ({ page, context }) => {
    await signInViaCookie(context);
    await page.goto('/upload');

    // Only the FIRST matching request is delayed — a second document's own extract call
    // (unrelated to what's being proven here) passes straight through unaffected.
    let capturedFirstUrl: string | null = null;
    await page.route('**/api/documents/*/extract', async (route) => {
      if (capturedFirstUrl === null) {
        capturedFirstUrl = route.request().url();
        await new Promise((resolve) => setTimeout(resolve, 3000));
      }
      await route.continue();
    });

    await page.setInputFiles('#statement-file', samplePdf('first-pdf'));
    await page.getByTestId('upload-submit').click();

    // The button must already be enabled again — not waiting on the still-delayed
    // extraction call (well under its 3s artificial delay above).
    await expect(page.getByTestId('upload-submit')).toBeEnabled({ timeout: 2000 });
    await expect(page.getByTestId('upload-submit')).toHaveText('Upload statement');

    await page.setInputFiles('#statement-file', samplePdf('second-pdf'));
    await page.getByTestId('upload-submit').click();
    await expect(page.getByTestId('toast-success')).toBeVisible();

    await page.unroute('**/api/documents/*/extract');
  });

  test('submitting without a file shows a validation message', async ({ page, context }) => {
    await signInViaCookie(context);
    await page.goto('/upload');

    await page.getByTestId('upload-submit').click();

    await expect(page.getByTestId('upload-validation-error')).toBeVisible();
    await expect(page.getByTestId('upload-validation-error')).toHaveText('Select a PDF statement.');
  });

  // The old "submitting without a legal entity shows a validation message (S4)" test is
  // gone, not just updated — Legal Entity is no longer user-selected (engineer-directed
  // simplification, 2026-08-30); every upload is assigned a fixed default client-side, so
  // that state can no longer occur through the UI. S4 (legal_entity_id must not be null)
  // is still enforced server-side in src/app/api/documents/route.ts, just no longer
  // reachable as a client validation message.

  // The next two tests hit the API directly (page.request, sharing the
  // signed-in page's cookies) rather than driving the UI form and comparing
  // table row counts — the uploaded-document list is shared, mutable state
  // that other tests write to concurrently under Playwright's default
  // parallel workers, so a total-row-count assertion is inherently flaky.
  // Asserting on the API response's own document_id is precise regardless
  // of what else is happening in the table at the same time.
  test('re-uploading the identical file (same bytes) is treated as a duplicate — no second row (G4)', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const fixed = {
      name: 'dupe-test.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from(`%PDF-1.4 fixed duplicate content ${Math.random()}`),
    };
    const entityId = 'vive-holdings';

    const first = await page.request.post('/api/documents', {
      multipart: { file: fixed, legalEntityId: entityId },
    });
    expect(first.status()).toBe(201);
    const firstBody = await first.json();
    expect(firstBody.duplicate).toBe(false);

    const second = await page.request.post('/api/documents', {
      multipart: { file: fixed, legalEntityId: entityId },
    });
    expect(second.status()).toBe(200);
    const secondBody = await second.json();
    expect(secondBody.duplicate).toBe(true);
    expect(secondBody.document.document_id).toBe(firstBody.document.document_id);
  });

  test('re-uploading the identical file under a different legal entity surfaces the mismatch, does not silently apply it', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const fixed = {
      name: 'dupe-entity-test.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from(`%PDF-1.4 fixed duplicate content for entity mismatch ${Math.random()}`),
    };

    const first = await page.request.post('/api/documents', {
      multipart: { file: fixed, legalEntityId: 'vive-holdings' },
    });
    const firstBody = await first.json();
    expect(firstBody.document.legal_entity_id).toBe('vive-holdings');

    const second = await page.request.post('/api/documents', {
      multipart: { file: fixed, legalEntityId: 'vive-mid-atlantic' },
    });
    const secondBody = await second.json();
    expect(secondBody.duplicate).toBe(true);
    expect(secondBody.legalEntityMismatch).toBe(true);
    // The originally-registered entity is preserved, not silently overwritten.
    expect(secondBody.document.legal_entity_id).toBe('vive-holdings');
  });

  test('a non-PDF file with no reported MIME type and a non-.pdf name is rejected, not silently accepted', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    await page.goto('/upload');

    // Regression test for the fix to the "file.type && ..." fail-open bug —
    // empty mimeType previously bypassed the PDF check entirely.
    await page.setInputFiles('#statement-file', {
      name: 'not-a-pdf.exe',
      mimeType: '',
      buffer: Buffer.from('definitely not a PDF'),
    });
    await page.getByTestId('upload-submit').click();

    await expect(page.getByTestId('toast-error')).toContainText('PDF files only');
  });

  test('uploaded-document list shows the uploaded file\'s own name, not the (unresolved) vendor', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    await page.goto('/upload');

    await page.setInputFiles('#statement-file', samplePdf('keystone'));
    await page.getByTestId('upload-submit').click();

    await expect(page.getByTestId('toast-success')).toBeVisible();
    // The row's own upload-timestamp ordering means the fresh row is the first in the
    // (most-recent-first) table — same landmark the old "Identifying…" placeholder used.
    const firstFilenameCell = page.locator('[data-testid^="document-filename-"]').first();
    await expect(firstFilenameCell).toHaveText(/keystone.*\.pdf/);
  });
});
