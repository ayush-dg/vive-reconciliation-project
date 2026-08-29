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

/** Directly seeds N synthetic exception rows (vendor + document + silver line + exception
 * each) — used only for the pagination-volume test, where driving 51 documents through the
 * real extraction/matching pipeline would be slow and pagination display logic doesn't
 * depend on how a row was produced (matching logic itself is Session 5's own test scope). */
function seedSyntheticExceptions(count: number, vendorSlugPrefix: string) {
  const db = getSqliteDb();
  for (let i = 0; i < count; i++) {
    const vendorId = crypto.randomUUID();
    const documentId = crypto.randomUUID();
    const lineId = crypto.randomUUID();
    const exceptionId = crypto.randomUUID();
    db.prepare(
      `INSERT INTO extracted_vendor_registry (vendor_id, vendor_slug, table_name, extraction_route) VALUES (?, ?, ?, NULL)`
    ).run(vendorId, `${vendorSlugPrefix}_${i}`, `extracted_stmt_${vendorSlugPrefix}_${i}`);
    db.prepare(`INSERT INTO extracted_document (document_id, content_sha256, legal_entity_id) VALUES (?, ?, 'vive-holdings')`).run(
      documentId,
      crypto.randomUUID()
    );
    db.prepare(
      `INSERT INTO silver_statement_line (line_id, document_id, vendor_id, amount, invoice_ref, normalized_invoice_ref, normalization_version)
       VALUES (?, ?, ?, ?, ?, ?, 'v1')`
    ).run(lineId, documentId, vendorId, 1, `INV-PAGE-${i}`, `INV-PAGE-${i}`);
    db.prepare(
      `INSERT INTO recon_exception (exception_id, statement_line_id, category, reason_codes, evidence) VALUES (?, ?, 'not_posted', '[]', '{}')`
    ).run(exceptionId, lineId);
  }
}

test.describe('Exceptions list screen', () => {
  test('exceptions list populates with real data from Session 5\'s matching output', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Exceptions_Populate_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    const invoiceRef = `INV-EXC-${crypto.randomUUID().slice(0, 8)}`;
    await makeRealNotPostedException(page, vendor, invoiceRef);

    await page.goto('/exceptions');
    await expect(page.getByText(vendor.toLowerCase(), { exact: false })).toBeVisible();
  });

  test('search by vendor name filters correctly', async ({ page, context }) => {
    await signInViaCookie(context);
    const uniqueVendor = `SearchFilterVendor${crypto.randomUUID().slice(0, 8)}`;
    await makeRealNotPostedException(page, uniqueVendor, `INV-SEARCH-${crypto.randomUUID().slice(0, 8)}`);

    await page.goto('/exceptions');
    await page.getByTestId('exceptions-search-input').fill(uniqueVendor.toLowerCase());
    await page.getByTestId('exceptions-search-submit').click();

    await expect(page.getByTestId('exceptions-table')).toContainText(uniqueVendor.toLowerCase());
    // A retrying expect(), not a one-shot .textContent() read — the search click fires an
    // async fetch (ExceptionsView.tsx's handleSearchSubmit doesn't await load()), so a
    // static read racing that fetch can observe the pre-search summary text.
    await expect(page.getByTestId('exceptions-pagination-summary')).toContainText('1 total');
  });

  // Challenge-review addition: vendor_slug values are underscore-delimited by
  // construction (vendorIdentification.ts's slugify()) — an unescaped SQL LIKE would let
  // "_" match any single character, so searching for one vendor's exact slug could also
  // match an unrelated vendor differing only at that position. Confirms the escaped
  // search matches ONLY the exact vendor, not both.
  test('a search term containing an underscore does not broaden the match via SQL LIKE wildcarding', async ({
    page,
    context,
  }) => {
    await signInViaCookie(context);
    const suffix = crypto.randomUUID().slice(0, 8);
    const exactVendor = `wildcard_test_${suffix}`; // the literal search term
    const decoyVendor = `wildcardXtest_${suffix}`; // differs only where "_" sits — matches if "_" is treated as a wildcard
    await makeRealNotPostedException(page, exactVendor, `INV-WC-EXACT-${suffix}`);
    await makeRealNotPostedException(page, decoyVendor, `INV-WC-DECOY-${suffix}`);

    await page.goto('/exceptions');
    await page.getByTestId('exceptions-search-input').fill(exactVendor);
    await page.getByTestId('exceptions-search-submit').click();

    await expect(page.getByTestId('exceptions-table')).toContainText(exactVendor);
    await expect(page.getByTestId('exceptions-pagination-summary')).toContainText('1 total');
    await expect(page.getByTestId('exceptions-table')).not.toContainText(decoyVendor);
  });

  test('pagination shows 50 rows per page when more than 50 exist', async ({ page, context }) => {
    await signInViaCookie(context);
    const prefix = `pg_vendor_${crypto.randomUUID().slice(0, 6)}`;
    seedSyntheticExceptions(51, prefix);

    await page.goto('/exceptions');
    await page.getByTestId('exceptions-search-input').fill(prefix);
    await page.getByTestId('exceptions-search-submit').click();

    await expect(page.getByTestId('exceptions-pagination-summary')).toContainText('51 total');
    const rows = page.locator('[data-testid^="exception-row-"]');
    await expect(rows).toHaveCount(50);

    await page.getByTestId('exceptions-next-page').click();
    await expect(page.locator('[data-testid^="exception-row-"]')).toHaveCount(1);
  });

  test('no bulk-selection UI is present', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Exceptions_NoBulk_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    await makeRealNotPostedException(page, vendor, `INV-NOBULK-${crypto.randomUUID().slice(0, 8)}`);

    await page.goto('/exceptions');
    await expect(page.locator('input[type="checkbox"]')).toHaveCount(0);
  });

  // Challenge-review addition: the client refetch (ExceptionsView.tsx's load()) previously
  // swallowed a failed API response with no error/retry UI at all — the table would just
  // keep showing stale data. Confirms the same global inline-error + Retry pattern now
  // surfaces, and that Retry recovers once the API is healthy again.
  test('a failed search/pagination refetch shows an inline error with Retry, which recovers', async ({ page, context }) => {
    await signInViaCookie(context);
    const vendor = `Exceptions_LoadError_Vendor_${crypto.randomUUID().slice(0, 8)}`;
    await makeRealNotPostedException(page, vendor, `INV-LOADERR-${crypto.randomUUID().slice(0, 8)}`);

    await page.goto('/exceptions');
    let shouldFail = true;
    await page.route('**/api/exceptions?*', (route) => {
      if (shouldFail) {
        shouldFail = false; // fail once, then let Retry succeed
        return route.fulfill({ status: 500, body: JSON.stringify({ error: 'simulated failure' }) });
      }
      return route.continue();
    });

    await page.getByTestId('exceptions-search-input').fill(vendor.toLowerCase());
    await page.getByTestId('exceptions-search-submit').click();
    // Shared InlineLoadError component (Task 6.4) — same testids as the global SSR error
    // boundary (error.tsx), not a screen-specific duplicate.
    await expect(page.getByTestId('error-boundary')).toBeVisible();

    await page.getByTestId('error-retry').click();
    await expect(page.getByTestId('error-boundary')).toHaveCount(0);
    await expect(page.getByTestId('exceptions-table')).toContainText(vendor.toLowerCase());
  });

  test('no possible_duplicate_correction category ever appears in the list', async ({ page, context }) => {
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

    await page.goto('/exceptions');
    await page.getByTestId('exceptions-search-input').fill(vendor.toLowerCase());
    await page.getByTestId('exceptions-search-submit').click();
    await expect(page.getByTestId('exceptions-table')).toContainText('Amount Mismatch');
  });
});
