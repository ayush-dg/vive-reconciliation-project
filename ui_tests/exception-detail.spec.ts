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

test.describe('Exception detail panel (two-pane vendor view)', () => {
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

    await page.goto(`/exceptions/${vendor.toLowerCase()}`);
    await expect(page.getByTestId('ccc-evidence-content')).toContainText(roNumber);
    await expect(page.getByTestId('ccc-evidence-empty')).toHaveCount(0);
  });

  // Challenge-review addition (carried over): recon.exception.evidence is a nullable
  // column (migration 005). JSON.parse(null) doesn't throw (it string-coerces to "null"
  // and returns JS null), so a NULL row previously bypassed exceptionDetail.ts's try/catch
  // entirely. No real code path writes a NULL evidence today, so this state is seeded
  // directly to confirm the panel degrades gracefully rather than crashing.
  test('an exception with a NULL evidence column degrades gracefully, not a crash', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `ExDetail_NullEvidence_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, `INV-NULLEV-${crypto.randomUUID().slice(0, 8)}`, '11.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);
    await page.request.post(`/api/documents/${documentId}/match`);
    const exceptionId = await findExceptionIdForDocument(documentId);

    const db = getSqliteDb();
    db.prepare('UPDATE recon_exception SET evidence = NULL WHERE exception_id = ?').run(exceptionId);

    await page.goto(`/exceptions/${vendor.toLowerCase()}`);
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

    await page.goto(`/exceptions/${vendor.toLowerCase()}`);
    await expect(page.getByTestId('ccc-evidence-empty')).toContainText('No CCC confirmation available');
  });

  test('an amount_mismatch exception shows both the statement and NetSuite values', async ({ page, context }) => {
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

    await page.goto(`/exceptions/${vendor.toLowerCase()}`);
    await expect(page.getByTestId('exception-detail-statement-amount')).toContainText('88.00');
    await expect(page.getByTestId('exception-detail-erp-amount')).toContainText('5.00');
  });

  test('a non-amount-mismatch exception does not show the ERP amount / difference fields', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `ExDetail_NotPosted_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, `INV-NOTPOSTED-DETAIL-${crypto.randomUUID().slice(0, 8)}`, '9.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);
    await page.request.post(`/api/documents/${documentId}/match`);

    await page.goto(`/exceptions/${vendor.toLowerCase()}`);
    await expect(page.getByTestId('exception-detail-category')).toHaveText('Missing in ERP');
    await expect(page.getByTestId('exception-detail-erp-amount')).toHaveCount(0);
  });

  // Engineer-directed (2026-09-01): Mark resolved / Flag for vendor / Skip are a
  // deliberate deviation from ARCHITECTURE.md D-C's "flat, ownerless list" — see
  // exceptionsList.ts's doc comment. Confirms the workflow actually updates state.
  test('"Mark resolved" updates the exception\'s status and the resolve-progress count', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `ExDetail_Resolve_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, `INV-RESOLVE-${crypto.randomUUID().slice(0, 8)}`, '15.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);
    await page.request.post(`/api/documents/${documentId}/match`);

    await page.goto(`/exceptions/${vendor.toLowerCase()}`);
    await expect(page.getByTestId('exceptions-resolve-count')).toHaveText('0 / 1 resolved');

    await page.getByTestId('exception-action-resolve').click();
    await expect(page.getByTestId('exceptions-resolve-count')).toHaveText('1 / 1 resolved');
  });

  test('"Exceptions" breadcrumb link navigates back to the vendor landing screen', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `ExDetail_BackLink_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, `INV-BACKLINK-${crypto.randomUUID().slice(0, 8)}`, '6.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);
    await page.request.post(`/api/documents/${documentId}/match`);

    await page.goto(`/exceptions/${vendor.toLowerCase()}`);
    await page.getByTestId('back-to-exceptions').click();
    await expect(page).toHaveURL('/exceptions');
  });
});
