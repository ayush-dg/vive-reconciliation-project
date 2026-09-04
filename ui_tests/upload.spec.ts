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

function samplePdf(label: string) {
  return {
    name: `${label}.pdf`,
    mimeType: 'application/pdf',
    buffer: Buffer.from(`%PDF-1.4 test fixture — ${label} — ${Math.random()}`),
  };
}

// A real, extractable statement (same pattern as home.spec.ts/document-detail.spec.ts) —
// samplePdf()'s fake buffers above never reach a real 'Extracted' badge, needed for
// ENH-001 Task 1.3's click-through tests.
function statementText(vendor: string, invoiceRef: string, amount: string) {
  return `VENDOR: ${vendor}\nPERIOD: 2026-08\nTOTAL: ${amount}\nINVOICE: ${invoiceRef} | RO: - | AMOUNT: ${amount} | DATE: 2026-08-01`;
}

// Deliberately mismatched TOTAL vs. line AMOUNT — deterministic arithmetic-validation
// failure on every attempt (same technique scripts/test_bounded_retry.mjs uses), so a
// single upload reaches the genuine 'Failed' badge (exhausted S7's 2-attempt bound, no
// extracted lines produced) without needing a multi-step retry setup.
function guaranteedFailureStatementText(vendor: string, invoiceRef: string) {
  return `VENDOR: ${vendor}\nPERIOD: 2026-08\nTOTAL: 999.00\nINVOICE: ${invoiceRef} | RO: - | AMOUNT: 10.00 | DATE: 2026-08-01`;
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

  // ENH-001 Task 1.3: click-through from Upload to a document's extracted lines.
  test('a click-through link to extracted lines appears once extraction completes', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Upload_ClickThrough_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const invoiceRef = `INV-CT-${crypto.randomUUID().slice(0, 8)}`;
    const res = await page.request.post('/api/documents', {
      multipart: {
        file: { name: `${vendor}.pdf`, mimeType: 'application/pdf', buffer: makeTestPdf(statementText(vendor, invoiceRef, '40.00')) },
        legalEntityId: 'vive-holdings',
      },
    });
    const documentId = (await res.json()).document.document_id as string;
    await page.request.post(`/api/documents/${documentId}/extract`);

    await page.goto('/upload');
    const link = page.getByTestId(`view-extracted-lines-${documentId}`);
    await expect(link).toBeVisible();
    await link.click();
    await expect(page).toHaveURL(`/documents/${documentId}`);
    await expect(page.getByTestId('document-detail-vendor')).toBeVisible();
  });

  test('no click-through is shown while extraction is still in progress', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Upload_StillProcessing_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const res = await page.request.post('/api/documents', {
      multipart: {
        file: { name: `${vendor}.pdf`, mimeType: 'application/pdf', buffer: makeTestPdf(statementText(vendor, 'INV-CT-PROC', '20.00')) },
        legalEntityId: 'vive-holdings',
      },
    });
    const documentId = (await res.json()).document.document_id as string;

    // Synthesize the "extraction genuinely in progress" state directly — same technique
    // document-detail.spec.ts uses for the pdfplumber_fallback case — rather than racing
    // a real timing window against this app's synchronous extraction pipeline. This is
    // exactly the G5 lock-acquisition transition (extraction.ts's own
    // `UPDATE extracted_document SET status = 'processing' WHERE status != 'processing'`),
    // with zero extraction_attempt rows yet — computeDocumentStatus's documented
    // zero-attempts branch classifies this as the 'Processing' badge.
    const db = getSqliteDb();
    db.prepare(`UPDATE extracted_document SET status = 'processing' WHERE document_id = ?`).run(documentId);

    await page.goto('/upload');
    const row = page.getByTestId(`document-row-${documentId}`);
    await expect(row.getByTestId(`status-badge-${documentId}`)).toHaveText('Processing');
    await expect(row.getByTestId(`view-extracted-lines-${documentId}`)).toHaveCount(0);
  });

  test('no click-through is shown when extraction genuinely fails (no lines to view)', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Upload_ExtractFail_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const res = await page.request.post('/api/documents', {
      multipart: {
        file: {
          name: `${vendor}.pdf`,
          mimeType: 'application/pdf',
          buffer: makeTestPdf(guaranteedFailureStatementText(vendor, 'INV-CT-FAIL')),
        },
        legalEntityId: 'vive-holdings',
      },
    });
    const documentId = (await res.json()).document.document_id as string;
    await page.request.post(`/api/documents/${documentId}/extract`);

    // Challenge agent Finding 1 (unverified assumption #1): assert open_exception_count
    // is actually 0 here, not just the badge label text — this is what distinguishes a
    // genuine extraction failure from a reconciliation exception (same badge/label for
    // both), and is the field the click-through condition itself branches on.
    const listRes = await page.request.get('/api/documents');
    const doc = (await listRes.json()).documents.find((d: { document_id: string }) => d.document_id === documentId);
    expect(doc.open_exception_count).toBe(0);

    await page.goto('/upload');
    const row = page.getByTestId(`document-row-${documentId}`);
    await expect(row.getByTestId(`status-badge-${documentId}`)).toHaveText('Failed — see Exceptions');
    await expect(row.getByTestId(`view-extracted-lines-${documentId}`)).toHaveCount(0);
  });

  // ENH-001 Task 1.3, challenge agent Finding 1: the Failed + open_exception_count > 0
  // branch (extraction succeeded, matching found a discrepancy, lines DO exist) was added
  // beyond the CC prompt's literal scope but had no test proving the link actually shows
  // in that case — all shipped tests only proved the open_exception_count === 0 (hide) side.
  test('click-through IS shown for a reconciliation exception — extraction succeeded, lines exist, badge reads Failed', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const vendor = `Upload_ReconException_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const invoiceRef = `INV-CT-RECEXC-${crypto.randomUUID().slice(0, 8)}`;
    const res = await page.request.post('/api/documents', {
      multipart: {
        file: { name: `${vendor}.pdf`, mimeType: 'application/pdf', buffer: makeTestPdf(statementText(vendor, invoiceRef, '30.00')) },
        legalEntityId: 'vive-holdings',
      },
    });
    const documentId = (await res.json()).document.document_id as string;
    await page.request.post(`/api/documents/${documentId}/extract`);
    // No bronze_netsuite_vendorbill row seeded — resolves to a NOT_POSTED exception, not
    // a genuine extraction failure. Extraction succeeded; lines genuinely exist.
    await page.request.post(`/api/documents/${documentId}/match`);

    const listRes = await page.request.get('/api/documents');
    const doc = (await listRes.json()).documents.find((d: { document_id: string }) => d.document_id === documentId);
    expect(doc.open_exception_count).toBeGreaterThan(0);

    await page.goto('/upload');
    const row = page.getByTestId(`document-row-${documentId}`);
    await expect(row.getByTestId(`status-badge-${documentId}`)).toHaveText('Failed — see Exceptions');
    const link = row.getByTestId(`view-extracted-lines-${documentId}`);
    await expect(link).toBeVisible();
    await link.click();
    await expect(page).toHaveURL(`/documents/${documentId}`);
  });

  // ENH-001 Task 1.4 (scope extended to this screen — see S1_SESSION_LOG.md Decision Log):
  // upload time displayed in IST, same known-instant technique as home.spec.ts's
  // equivalent test, also exercising the naive-string UTC-parsing fix.
  test('upload time displays correctly converted to IST', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Upload_IST_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const res = await page.request.post('/api/documents', {
      multipart: { file: samplePdf(vendor), legalEntityId: 'vive-holdings' },
    });
    const documentId = (await res.json()).document.document_id as string;

    // 2026-01-15 08:05:37 UTC -> 13:35:37 IST (UTC+5:30).
    const db = getSqliteDb();
    db.prepare(`UPDATE extracted_document SET upload_timestamp = '2026-01-15 08:05:37' WHERE document_id = ?`).run(documentId);

    await page.goto('/upload');
    const row = page.getByTestId(`document-row-${documentId}`);
    await expect(row).toContainText('1/15/2026, 1:35:37 PM');

    // Challenge agent Finding 2: confirm the raw column is unaffected by display
    // formatting — see home.spec.ts's equivalent assertion.
    const stored = db.prepare(`SELECT upload_timestamp FROM extracted_document WHERE document_id = ?`).get(documentId) as {
      upload_timestamp: string;
    };
    expect(stored.upload_timestamp).toBe('2026-01-15 08:05:37');
  });
});
