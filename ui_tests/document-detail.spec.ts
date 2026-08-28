import crypto from 'node:crypto';
import { test, expect } from '@playwright/test';
import { TEST_USERNAME, TEST_SESSION_SECRET } from './global-setup';
import { SESSION_COOKIE_NAME, signSessionToken } from '../src/lib/session';
import { getSqliteDb } from '../src/lib/db';
import { ensureVendorStmtTable } from '../src/lib/vendorSchema';
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
      file: { name: `doc-detail-test-${crypto.randomUUID()}.pdf`, mimeType: 'application/pdf', buffer: makeTestPdf(text) },
      legalEntityId: 'vive-holdings',
    },
  });
  const body = await res.json();
  return body.document.document_id as string;
}

test.describe('Document Detail screen', () => {
  test('navigating from Home\'s "View statement" opens this screen with the correct document\'s rows', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const vendor = `DocDetail_Nav_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const invoiceRef = `INV-DD-${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, invoiceRef, '15.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);

    await page.goto(`/documents/${documentId}`);
    // The screen shows vendor_slug (documentDetail.ts) — trimmed/lowercased/underscored
    // by vendorIdentification.ts's slugify(), not the raw vendor-name string.
    await expect(page.getByTestId('document-detail-vendor')).toHaveText(vendor.toLowerCase());
    await expect(page.getByTestId(/^statement-line-/)).toBeVisible();
  });

  test('extraction summary strip shows correct counts by provider (Claude-primary path)', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `DocDetail_Summary_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, 'INV-DD-SUM', '25.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);

    await page.goto(`/documents/${documentId}`);
    await expect(page.getByTestId('provider-count-claude_sonnet')).toContainText('1');
    await expect(page.getByTestId('provider-count-python_library_pdfplumber')).toHaveCount(0);
    await expect(page.getByTestId('provider-count-pdfplumber_fallback')).toHaveCount(0);
  });

  test('a document extracted via the known-vendor deterministic path shows 100% python_library_pdfplumber, no Claude/OCR-fallback counts', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const db = getSqliteDb();
    const vendorSlug = `doc_detail_det_vendor_${crypto.randomUUID().slice(0, 8)}`;
    const vendorId = crypto.randomUUID();
    const tableName = await ensureVendorStmtTable(vendorSlug);
    db.prepare(
      `INSERT INTO extracted_vendor_registry (vendor_id, vendor_slug, table_name, extraction_route) VALUES (?, ?, ?, 'deterministic')`
    ).run(vendorId, vendorSlug, tableName);

    // The vendor-name text must slugify to the registered slug for routing to pick the
    // deterministic path (vendorIdentification.ts's slugify()).
    const vendorNameForSlug = vendorSlug.replace(/_/g, ' ');
    const documentId = await uploadFixture(page, statementText(vendorNameForSlug, 'INV-DD-DET', '35.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);

    await page.goto(`/documents/${documentId}`);
    await expect(page.getByTestId('provider-count-python_library_pdfplumber')).toContainText('1');
    await expect(page.getByTestId('provider-count-claude_sonnet')).toHaveCount(0);
    await expect(page.getByTestId('provider-count-pdfplumber_fallback')).toHaveCount(0);
  });

  test('a document with some AI-failure fallback rows shows a non-zero OCR-fallback count', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `DocDetail_Fallback_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, 'INV-DD-FB', '45.00'));

    // pdfplumber_fallback is a documented provider value no live code path in this build
    // produces yet (flagged as an Out of Scope Observation, sessions/S03_SESSION_LOG.md) —
    // synthesized directly, same technique extract-trigger.spec.ts uses for the Retrying
    // badge, to confirm the DISPLAY layer labels it correctly when it does occur.
    const db = getSqliteDb();
    db.prepare(
      `INSERT INTO extracted_extraction_attempt (attempt_id, document_id, attempt_no, provider_used, arithmetic_pass, structural_pass)
       VALUES (?, ?, 1, 'pdfplumber_fallback', 1, 1)`
    ).run(crypto.randomUUID(), documentId);

    await page.goto(`/documents/${documentId}`);
    await expect(page.getByTestId('provider-count-pdfplumber_fallback')).toContainText('1');
    await expect(page.getByTestId('provider-count-pdfplumber_fallback')).toContainText('via OCR fallback');
  });

  test('Extract/Reconcile actions appear only when applicable to the document\'s current status', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `DocDetail_Actions_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, 'INV-DD-ACT', '55.00'));

    await page.goto(`/documents/${documentId}`);
    await expect(page.getByTestId('document-detail-extract-button')).toBeVisible();
    await expect(page.getByTestId('document-detail-reconcile-button')).toHaveCount(0);

    await page.getByTestId('document-detail-extract-button').click();
    await expect(page.getByTestId('toast-success')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('document-detail-extract-button')).toHaveCount(0);
    await expect(page.getByTestId('document-detail-reconcile-button')).toBeVisible();
  });

  // Challenge-review regression (Tasks 6.1/6.5): a document whose matching run produces
  // an open exception (no NetSuite row exists for its invoice) must show "Failed — see
  // Exceptions", not "Reconciled" — and once that terminal state is reached, the
  // Reconcile button must disappear rather than staying clickable forever with a
  // misleading repeat "success" toast (documentStatus.ts's badge logic previously
  // reported "Reconciled" for ANY match existing, not ALL lines matched).
  test('a document whose matching run produces an open exception shows "Failed — see Exceptions", and Reconcile disappears', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const vendor = `DocDetail_ExceptionOutcome_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const documentId = await uploadFixture(page, statementText(vendor, `INV-DD-EXC-${crypto.randomUUID().slice(0, 8)}`, '65.00'));
    await page.request.post(`/api/documents/${documentId}/extract`);
    // No bronze_netsuite_vendorbill row seeded for this invoice — the line resolves to a
    // NOT_POSTED exception, not a match.
    await page.request.post(`/api/documents/${documentId}/match`);

    await page.goto(`/documents/${documentId}`);
    await expect(page.getByTestId('document-detail-status-badge')).toHaveText('Failed — see Exceptions');
    await expect(page.getByTestId('document-detail-reconcile-button')).toHaveCount(0);
  });
});
