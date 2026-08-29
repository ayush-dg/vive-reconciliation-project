import crypto from 'node:crypto';
import { test, expect } from '@playwright/test';
import { TEST_USERNAME, TEST_SESSION_SECRET } from './global-setup';
import { SESSION_COOKIE_NAME, signSessionToken } from '../src/lib/session';
import { getSqliteDb } from '../src/lib/db';
import { ensureNetsuiteVendorBillFixtureTable, seedNetsuiteVendorBillRow } from '../scripts/netsuiteVendorBillFixture.mjs';
import { ensureCccRepairOrderFixtureTable, seedCccRepairOrderRow } from '../scripts/cccRepairOrderFixture.mjs';
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
      file: { name: `exception-detail-test-${crypto.randomUUID()}.pdf`, mimeType: 'application/pdf', buffer: makeTestPdf(text) },
      legalEntityId: 'vive-holdings',
    },
  });
  const body = await res.json();
  return body.document.document_id as string;
}

async function findExceptionIdForDocument(documentId: string): Promise<string> {
  const db = getSqliteDb();
  const row = db
    .prepare(`SELECT e.exception_id AS id FROM recon_exception e JOIN silver_statement_line sl ON sl.line_id = e.statement_line_id WHERE sl.document_id = ?`)
    .get(documentId) as { id: string };
  return row.id;
}

test.describe('Exception Detail screen', () => {
  test('an exception with CCC evidence shows the Related panel populated', async ({ page, context }) => {
    await signInViaCookie(context);
    const db = getSqliteDb();
    ensureCccRepairOrderFixtureTable();
    const vendor = `ExDetail_Ccc_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const amount = '61.00';
    const roNumber = `RO-${crypto.randomUUID().slice(0, 8)}`;
    seedCccRepairOrderRow(db, { roNumber, vendorName: 'x', amount: 61, runId: 'ex-detail-ccc-run', extractedAt: '2026-08-27T00:00:00Z' });

    const documentId = await uploadFixture(page, statementText(vendor, `INV-CCC-${crypto.randomUUID().slice(0, 8)}`, amount));
    await page.request.post(`/api/documents/${documentId}/extract`);
    await page.request.post(`/api/documents/${documentId}/match`);
    const exceptionId = await findExceptionIdForDocument(documentId);

    await page.goto(`/exceptions/${exceptionId}`);
    await expect(page.getByTestId('ccc-evidence-content')).toContainText(roNumber);
    await expect(page.getByTestId('ccc-evidence-empty')).toHaveCount(0);
  });

  // Challenge-review addition: recon.exception.evidence is a nullable column
  // (migration 005). JSON.parse(null) doesn't throw (it string-coerces to "null" and
  // returns JS null), so a NULL row previously bypassed exceptionDetail.ts's try/catch
  // entirely and would have thrown uncaught on evidence.residual/evidence.deterministic
  // access. No real code path writes a NULL evidence today (exceptionWriter.ts always
  // JSON.stringifies it), so this state is seeded directly to confirm the page degrades
  // gracefully rather than crashing, per exceptionDetail.ts's own stated guarantee.
  test('an exception with a NULL evidence column degrades gracefully, not a crash', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `ExDetail_NullEvidence_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, `INV-NULLEV-${crypto.randomUUID().slice(0, 8)}`, '11.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);
    await page.request.post(`/api/documents/${documentId}/match`);
    const exceptionId = await findExceptionIdForDocument(documentId);

    const db = getSqliteDb();
    db.prepare('UPDATE recon_exception SET evidence = NULL WHERE exception_id = ?').run(exceptionId);

    await page.goto(`/exceptions/${exceptionId}`);
    await expect(page.getByTestId('exception-detail-category')).toBeVisible();
    await expect(page.getByTestId('ccc-evidence-empty')).toContainText('No CCC confirmation available');
    await expect(page.getByTestId('error-boundary')).toHaveCount(0);
  });

  test('an exception without CCC evidence shows "No CCC confirmation available"', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `ExDetail_NoCcc_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, `INV-NOCCC-${crypto.randomUUID().slice(0, 8)}`, '77.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);
    await page.request.post(`/api/documents/${documentId}/match`);
    const exceptionId = await findExceptionIdForDocument(documentId);

    await page.goto(`/exceptions/${exceptionId}`);
    await expect(page.getByTestId('ccc-evidence-empty')).toContainText('No CCC confirmation available');
  });

  test('an amount_mismatch exception shows the expandable section with both the statement and NetSuite values', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const db = getSqliteDb();
    ensureNetsuiteVendorBillFixtureTable();
    const vendor = `ExDetail_Mismatch_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const invoiceRef = `INV-MISMATCH-DETAIL-${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, invoiceRef, '88.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);

    seedNetsuiteVendorBillRow(db, {
      transactionId: crypto.randomUUID(),
      billDocumentNumber: invoiceRef,
      amount: 5.0,
      runId: 'ex-detail-mismatch-run',
      extractedAt: '2026-08-27T00:00:00Z',
    });
    await page.request.post(`/api/documents/${documentId}/match`);
    const exceptionId = await findExceptionIdForDocument(documentId);

    await page.goto(`/exceptions/${exceptionId}`);
    const drilldown = page.getByTestId('amount-mismatch-drilldown');
    await expect(drilldown).toBeVisible();
    // Collapsed by default (UI_SURFACE.md) — a native <details> element, so its content
    // is genuinely hidden (not just off-screen) until expanded via its <summary>.
    await drilldown.locator('summary').click();
    await expect(page.getByTestId('amount-mismatch-statement-value')).toContainText('88.00');
    await expect(page.getByTestId('amount-mismatch-netsuite-value')).toContainText('5.00');
    await expect(page.getByTestId('amount-mismatch-as-of')).toBeVisible();
  });

  test('a non-amount-mismatch exception does not show the amount-mismatch drill-down section', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `ExDetail_NotPosted_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, `INV-NOTPOSTED-DETAIL-${crypto.randomUUID().slice(0, 8)}`, '9.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);
    await page.request.post(`/api/documents/${documentId}/match`);
    const exceptionId = await findExceptionIdForDocument(documentId);

    await page.goto(`/exceptions/${exceptionId}`);
    await expect(page.getByTestId('exception-detail-category')).toHaveText('Not Posted');
    await expect(page.getByTestId('amount-mismatch-drilldown')).toHaveCount(0);
  });

  test('no approve/dispute action buttons exist anywhere on this screen', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `ExDetail_NoActions_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, `INV-NOACTIONS-${crypto.randomUUID().slice(0, 8)}`, '3.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);
    await page.request.post(`/api/documents/${documentId}/match`);
    const exceptionId = await findExceptionIdForDocument(documentId);

    await page.goto(`/exceptions/${exceptionId}`);
    await expect(page.getByText('Approve', { exact: false })).toHaveCount(0);
    await expect(page.getByText('Dispute', { exact: false })).toHaveCount(0);
  });

  test('"Back to list" navigates to /exceptions', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `ExDetail_BackLink_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, `INV-BACKLINK-${crypto.randomUUID().slice(0, 8)}`, '6.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);
    await page.request.post(`/api/documents/${documentId}/match`);
    const exceptionId = await findExceptionIdForDocument(documentId);

    await page.goto(`/exceptions/${exceptionId}`);
    await page.getByTestId('back-to-exceptions').click();
    await expect(page).toHaveURL('/exceptions');
  });
});
