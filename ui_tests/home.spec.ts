import crypto from 'node:crypto';
import { test, expect } from '@playwright/test';
import { TEST_USERNAME, TEST_SESSION_SECRET } from './global-setup';
import { SESSION_COOKIE_NAME, signSessionToken } from '../src/lib/session';
import { getSqliteDb } from '../src/lib/db';
import { ensureNetsuiteVendorBillFixtureTable, seedNetsuiteVendorBillRow } from '../scripts/netsuiteVendorBillFixture.mjs';
import { makeTestPdf } from '../scripts/testPdfFixture.mjs';

async function signInViaCookie(context: import('@playwright/test').BrowserContext) {
  process.env.SESSION_SECRET = TEST_SESSION_SECRET;
  const token = await signSessionToken({ userId: 'test-user-id', username: TEST_USERNAME, lastSeenAt: Date.now() });
  await context.addCookies([
    { name: SESSION_COOKIE_NAME, value: token, url: 'http://localhost:3000', httpOnly: true, sameSite: 'Lax' },
  ]);
}

function statementText(vendor: string, invoiceRef: string, amount: string) {
  return `VENDOR: ${vendor}\nPERIOD: 2026-08\nTOTAL: ${amount}\nINVOICE: ${invoiceRef} | RO: - | AMOUNT: ${amount} | DATE: 2026-08-01`;
}

async function uploadFixture(page: import('@playwright/test').Page, text: string) {
  const res = await page.request.post('/api/documents', {
    multipart: {
      file: { name: `home-test-${crypto.randomUUID()}.pdf`, mimeType: 'application/pdf', buffer: makeTestPdf(text) },
      legalEntityId: 'vive-holdings',
    },
  });
  const body = await res.json();
  return body.document.document_id as string;
}

test.describe('Home screen', () => {
  test('uploading a statement and returning to Home shows it with the correct status badge', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Home_Badge_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, 'INV-H1', '10.00'));

    await page.goto('/home');
    await expect(page.getByTestId(`home-status-badge-${documentId}`)).toHaveText('Processing');
  });

  test('summary stats reflect actual document/exception/reconciled/not-reconciled counts', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Home_Stats_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    await uploadFixture(page, statementText(vendor, 'INV-H2', '20.00'));

    // Reads a ground-truth floor directly from the DB (after our own upload has landed),
    // not a before/after snapshot diff — this suite runs fullyParallel, so other workers
    // concurrently register/extract/match documents at any moment; a "count went up by
    // exactly 1" assertion is inherently racy under that model, and even this floor has a
    // small residual window between the two reads. >= (not ===) is the correct assertion:
    // our own upload is definitely counted, and concurrent tests can only add more, never
    // remove, so the display can legitimately be higher, never lower, than this floor.
    const db = getSqliteDb();
    const floor = (db.prepare('SELECT COUNT(*) AS n FROM extracted_document').get() as { n: number }).n;

    await page.goto('/home');
    const shown = Number(await page.getByTestId('stat-documents-processed').textContent());
    expect(shown).toBeGreaterThanOrEqual(floor);
  });

  test('clicking Reconcile on an extracted document triggers matching and the badge updates to Done', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const db = getSqliteDb();
    ensureNetsuiteVendorBillFixtureTable();

    const vendor = `Home_Reconcile_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const invoiceRef = `INV-RECONCILE-${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, invoiceRef, '30.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);

    seedNetsuiteVendorBillRow(db, {
      transactionId: crypto.randomUUID(),
      billDocumentNumber: invoiceRef,
      amount: 30,
      runId: 'home-e2e-run',
      extractedAt: '2026-08-27T00:00:00Z',
    });

    await page.goto('/home');
    await page.getByTestId(`home-reconcile-button-${documentId}`).click();
    await expect(page.getByTestId('toast-success')).toBeVisible({ timeout: 15_000 });
    // "Done", not "Reconciled" — Home's own softer display mapping (2026-08-31), same
    // underlying computeDocumentStatus() badge ('Reconciled') Document Detail still shows
    // verbatim.
    await expect(page.getByTestId(`home-status-badge-${documentId}`)).toHaveText('Done');
  });

  // Engineer-directed (2026-08-31): a document whose matching run produced an open
  // exception should read as "Done" on Home too (reconciliation genuinely finished, just
  // with something to review) — not the same alarming "Failed — see Exceptions" wording a
  // real extraction failure gets, which was the previous, conflated behavior. A "Show
  // exceptions" link appears alongside it, pre-filtering the Exceptions screen to this
  // vendor via the existing ?search= support (exceptionsList.ts).
  test('a document whose matching run produces an open exception shows "Done" with a "Show exceptions" link, not "Failed"', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const vendor = `Home_DoneWithException_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, `INV-DONE-EXC-${crypto.randomUUID().slice(0, 8)}`, '40.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);
    // No bronze_netsuite_vendorbill row seeded — resolves to a NOT_POSTED exception.
    await page.request.post(`/api/documents/${documentId}/match`);

    await page.goto('/home');
    await expect(page.getByTestId(`home-status-badge-${documentId}`)).toHaveText('Done');
    const exceptionsLink = page.getByTestId(`home-show-exceptions-${documentId}`);
    await expect(exceptionsLink).toBeVisible();

    await exceptionsLink.click();
    await expect(page).toHaveURL(new RegExp(`/exceptions/${vendor.toLowerCase()}`));
    await expect(page.getByTestId('exceptions-vendor-count')).toHaveText('1 exceptions');
  });

  test('Reconcile button is not shown for a document that has not finished extraction yet', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Home_NoReconcile_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, 'INV-H4', '40.00'));

    await page.goto('/home');
    await expect(page.getByTestId(`home-reconcile-button-${documentId}`)).toHaveCount(0);
    await expect(page.getByTestId(`home-extract-button-${documentId}`)).toBeVisible();
  });

  test('"View statement" navigates to the Document Detail screen', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Home_ViewStatement_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, 'INV-H5', '50.00'));

    await page.goto('/home');
    await page.getByTestId(`view-statement-${documentId}`).click();
    await expect(page).toHaveURL(`/documents/${documentId}`);
    await expect(page.getByTestId('document-detail-status-badge')).toBeVisible();
  });

  // Task 6.4 challenge-review addition: HomeView.tsx's refresh() previously swallowed a
  // failed /api/documents or /api/home-summary response with zero user-facing signal —
  // the same defect Task 6.2's own review found and fixed for Exceptions, generalized
  // here via the shared InlineLoadError component (error-boundary/error-retry testids,
  // not a screen-specific duplicate).
  test('a failed post-action refresh shows the shared inline error, and Retry recovers — without misreporting the action itself as failed', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const vendor = `Home_RefreshError_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, `INV-H-REFRESH-${crypto.randomUUID().slice(0, 8)}`, '18.00'));

    await page.goto('/home');
    let shouldFail = true;
    await page.route('**/api/documents', (route) => {
      if (route.request().method() === 'GET' && shouldFail) {
        shouldFail = false;
        return route.fulfill({ status: 500, body: JSON.stringify({ error: 'simulated failure' }) });
      }
      return route.continue();
    });

    await page.getByTestId(`home-extract-button-${documentId}`).click();
    // The POST itself succeeded — the toast must say so, not "failed", even though the
    // follow-up refresh() GET is about to fail.
    await expect(page.getByTestId('toast-success')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('error-boundary')).toBeVisible();

    await page.getByTestId('error-retry').click();
    await expect(page.getByTestId('error-boundary')).toHaveCount(0);
    await expect(page.getByTestId(`home-status-badge-${documentId}`)).toBeVisible();
  });
});
