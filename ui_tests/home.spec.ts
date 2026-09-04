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

  test('clicking Reconcile on an extracted document triggers matching and the badge updates to Recon done', async ({
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
    // "Recon done", not "Reconciled" — Home's own softer display mapping (2026-08-31,
    // renamed 2026-09-03 per ENH-001 Task 1.1), same underlying computeDocumentStatus()
    // badge ('Reconciled') Document Detail still shows verbatim.
    const badge = page.getByTestId(`home-status-badge-${documentId}`);
    await expect(badge).toHaveText('Recon done');
    // Task 1.1 CC prompt: only the label strings change, badgeClass must be untouched.
    await expect(badge).toHaveClass(/reconciled/);
  });

  test('an extracted document (not yet reconciled) shows "Extraction success" on Home', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const vendor = `Home_ExtractionSuccess_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, `INV-EXTRACTED-${crypto.randomUUID().slice(0, 8)}`, '25.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);

    await page.goto('/home');
    // "Extraction success", not "Success" — ENH-001 Task 1.1 rename, so it's clear this
    // reflects the extraction stage completing, not reconciliation.
    const badge = page.getByTestId(`home-status-badge-${documentId}`);
    await expect(badge).toHaveText('Extraction success');
    // Task 1.1 CC prompt: only the label strings change, badgeClass must be untouched.
    await expect(badge).toHaveClass(/extracted/);
  });

  // Engineer-directed (2026-08-31): a document whose matching run produced an open
  // exception should read as "Recon done" on Home too (reconciliation genuinely finished,
  // just with something to review) — not the same alarming "Failed — see Exceptions"
  // wording a real extraction failure gets, which was the previous, conflated behavior. A
  // "Show exceptions" link appears alongside it, pre-filtering the Exceptions screen to
  // this vendor via the existing ?search= support (exceptionsList.ts). Label renamed
  // 'Done' -> 'Recon done' 2026-09-03 per ENH-001 Task 1.1.
  test('a document whose matching run produces an open exception shows "Recon done" with a "Show exceptions" link, not "Failed"', async ({
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
    await expect(page.getByTestId(`home-status-badge-${documentId}`)).toHaveText('Recon done');
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

  // ENH-001 Task 1.4: upload time displayed in IST (Asia/Kolkata), fixed. A known UTC
  // instant (not "some value rendered") pins the actual conversion, and specifically
  // exercises the naive-string UTC-parsing fix (upload_timestamp is stored as
  // "YYYY-MM-DD HH:MM:SS" with no timezone marker — see formatUploadTimestamp's comment).
  test('upload time displays correctly converted to IST', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Home_IST_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, 'INV-IST', '12.00'));

    // 2026-01-15 08:05:37 UTC -> 13:35:37 IST (UTC+5:30).
    const db = getSqliteDb();
    db.prepare(`UPDATE extracted_document SET upload_timestamp = '2026-01-15 08:05:37' WHERE document_id = ?`).run(documentId);

    await page.goto('/home');
    const row = page.getByTestId(`home-document-row-${documentId}`);
    await expect(row).toContainText('1/15/2026, 1:35:37 PM');

    // Challenge agent Finding 2: the task's own regression case ("underlying stored
    // value is unaffected") had no DB-level assertion — only the rendered string was
    // checked. Confirm the raw column is still the unconverted naive string post-render.
    const stored = db.prepare(`SELECT upload_timestamp FROM extracted_document WHERE document_id = ?`).get(documentId) as {
      upload_timestamp: string;
    };
    expect(stored.upload_timestamp).toBe('2026-01-15 08:05:37');
  });

  // Challenge agent Finding 1: the other IST test only exercised a single mid-day
  // instant. A UTC time in the ~18:30-23:59 window crosses into the *next* IST calendar
  // day — the classic timezone-conversion failure mode (date/month/year rollover), left
  // entirely unverified otherwise.
  test('upload time IST conversion correctly rolls over to the next calendar day', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Home_ISTRollover_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, 'INV-IST-ROLL', '13.00'));

    // 2026-01-15 20:00:00 UTC -> 2026-01-16 01:30:00 IST (UTC+5:30) — crosses midnight.
    const db = getSqliteDb();
    db.prepare(`UPDATE extracted_document SET upload_timestamp = '2026-01-15 20:00:00' WHERE document_id = ?`).run(documentId);

    await page.goto('/home');
    const row = page.getByTestId(`home-document-row-${documentId}`);
    await expect(row).toContainText('1/16/2026, 1:30:00 AM');
  });
});
