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
      file: { name: `exceptions-test-${crypto.randomUUID()}.pdf`, mimeType: 'application/pdf', buffer: makeTestPdf(text) },
      legalEntityId: 'vive-holdings',
    },
  });
  const body = await res.json();
  return body.document.document_id as string;
}

/** Real end-to-end NOT_POSTED exception via extract -> match (no NetSuite row exists for
 * this invoice ref) — exercises the actual pipeline, not a synthesized row. */
async function makeRealNotPostedException(page: import('@playwright/test').Page, vendor: string, invoiceRef: string) {
  const documentId = await uploadFixture(page, statementText(vendor, invoiceRef, '12.34'));
  await page.request.post(`/api/documents/${documentId}/extract`);
  await page.request.post(`/api/documents/${documentId}/match`);
}

test.describe('Exceptions landing screen', () => {
  test('vendor list populates with real data from the matching pipeline', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Exceptions_Populate_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    await makeRealNotPostedException(page, vendor, `INV-EXC-${crypto.randomUUID().slice(0, 8)}`);

    await page.goto('/exceptions');
    await expect(page.getByTestId(`exceptions-vendor-link-${vendor.toLowerCase()}`)).toBeVisible();
  });

  test('the vendor search box filters the list client-side', async ({ page, context }) => {
    await signInViaCookie(context);
    const uniqueVendor = `SearchFilterVendor${crypto.randomUUID().slice(0, 8)}`;
    const otherVendor = `OtherVendor${crypto.randomUUID().slice(0, 8)}`;
    await makeRealNotPostedException(page, uniqueVendor, `INV-SEARCH-${crypto.randomUUID().slice(0, 8)}`);
    await makeRealNotPostedException(page, otherVendor, `INV-SEARCH-OTHER-${crypto.randomUUID().slice(0, 8)}`);

    await page.goto('/exceptions');
    await page.getByTestId('exceptions-vendor-search-input').fill(uniqueVendor.toLowerCase());

    await expect(page.getByTestId(`exceptions-vendor-link-${uniqueVendor.toLowerCase()}`)).toBeVisible();
    await expect(page.getByTestId(`exceptions-vendor-link-${otherVendor.toLowerCase()}`)).toHaveCount(0);
  });

  test('clicking a vendor navigates to that vendor\'s two-pane exception view', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Exceptions_Navigate_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    await makeRealNotPostedException(page, vendor, `INV-NAV-${crypto.randomUUID().slice(0, 8)}`);

    await page.goto('/exceptions');
    await page.getByTestId(`exceptions-vendor-link-${vendor.toLowerCase()}`).click();
    await expect(page).toHaveURL(`/exceptions/${vendor.toLowerCase()}`);
    await expect(page.getByTestId('exceptions-vendor-count')).toHaveText('1 exceptions');
  });

  test('no bulk-selection UI is present', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Exceptions_NoBulk_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    await makeRealNotPostedException(page, vendor, `INV-NOBULK-${crypto.randomUUID().slice(0, 8)}`);

    await page.goto('/exceptions');
    await expect(page.locator('input[type="checkbox"]')).toHaveCount(0);
  });

  // Challenge-review addition (carried over from the flat-list screen): a failed refetch
  // must not leave the table silently showing stale/wrong data with no signal. The vendor
  // list is server-rendered on load, so the only client fetch is the explicit Refresh
  // button — exercised here instead of a search-triggered one.
  test('a failed refresh shows an inline error with Retry, which recovers', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Exceptions_LoadError_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    await makeRealNotPostedException(page, vendor, `INV-LOADERR-${crypto.randomUUID().slice(0, 8)}`);

    await page.goto('/exceptions');
    let shouldFail = true;
    await page.route('**/api/exceptions', (route) => {
      if (route.request().method() === 'GET' && shouldFail) {
        shouldFail = false;
        return route.fulfill({ status: 500, body: JSON.stringify({ error: 'simulated failure' }) });
      }
      return route.continue();
    });

    await page.getByTestId('exceptions-vendor-refresh').click();
    await expect(page.getByTestId('error-boundary')).toBeVisible();

    await page.getByTestId('error-retry').click();
    await expect(page.getByTestId('error-boundary')).toHaveCount(0);
    await expect(page.getByTestId(`exceptions-vendor-link-${vendor.toLowerCase()}`)).toBeVisible();
  });

  test('no possible_duplicate_correction category ever appears', async ({ page, context }) => {
    await signInViaCookie(context);
    await page.goto('/exceptions');
    await expect(page.getByText('possible_duplicate_correction', { exact: false })).toHaveCount(0);
    await expect(page.getByText('Possible Duplicate', { exact: false })).toHaveCount(0);
  });

  test('an amount_mismatch exception shows correctly through the real pipeline', async ({ page, context }) => {
    await signInViaCookie(context);
    const db = getSqliteDb();
    ensureNetsuiteVendorBillFixtureTable();
    const vendor = `Exceptions_AmountMismatch_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const invoiceRef = `INV-MISMATCH-${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, invoiceRef, '99.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);

    seedNetsuiteVendorBillRow(db, {
      transactionId: crypto.randomUUID(),
      billDocumentNumber: invoiceRef,
      amount: 1.0, // deliberately different from the statement's 99.00
      runId: 'exceptions-mismatch-run',
      extractedAt: '2026-08-27T00:00:00Z',
    });
    await page.request.post(`/api/documents/${documentId}/match`);

    await page.goto(`/exceptions/${vendor.toLowerCase()}`);
    await expect(page.getByTestId('exception-detail-category')).toHaveText('Amount mismatch');
    await expect(page.getByTestId('exception-detail-statement-amount')).toContainText('99.00');
    await expect(page.getByTestId('exception-detail-erp-amount')).toContainText('1.00');
  });
});
