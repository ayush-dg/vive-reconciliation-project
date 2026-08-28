// Task 3.1 test cases — vendor identification, extraction routing, attempt recording.
import crypto from 'node:crypto';
import { getSqliteDb, closeDb } from '../src/lib/db.ts';
import { runMigrations } from '../src/lib/migrate.ts';
import { registerDocument } from '../src/lib/documents.ts';
import { ensureVendorStmtTable } from '../src/lib/vendorSchema.ts';
import { identifyAndExtract } from '../src/lib/vendorIdentification.ts';
import { runExtractionPipeline } from '../src/lib/extractionPipeline.ts';
import { makeTestPdf, makeStatementText } from './testPdfFixture.mjs';

let failures = 0;
function check(label, condition) {
  if (condition) {
    console.log(`PASS: ${label}`);
  } else {
    console.error(`FAIL: ${label}`);
    failures++;
  }
}

runMigrations();
const db = getSqliteDb();

function registerTestDoc(text, legalEntityId = 'entity-1') {
  const bytes = makeTestPdf(text);
  const { document } = registerDocument(bytes, legalEntityId);
  return document.documentId;
}

// --- TC-1: document matching a registered vendor's signature routes to
// deterministic pdfplumber path, lands in extracted.stmt_<vendor_slug> ---
{
  const vendorId = crypto.randomUUID();
  const vendorSlug = 'fred_beans';
  const tableName = await ensureVendorStmtTable(vendorSlug);
  db.prepare(
    `INSERT INTO extracted_vendor_registry (vendor_id, vendor_slug, table_name, extraction_route) VALUES (?, ?, ?, 'deterministic')`
  ).run(vendorId, vendorSlug, tableName);

  const text = makeStatementText({
    vendor: 'Fred Beans',
    total: '100.00',
    lines: [{ invoiceRef: 'INV-1', roNumber: null, amount: '100.00', date: '2026-07-01' }],
  });
  const documentId = registerTestDoc(text);
  const pdfBytes = makeTestPdf(text);
  const result = await identifyAndExtract(documentId, 'entity-1', pdfBytes);

  check('TC-1: routes to deterministic path for a known vendor', result.provider === 'python_library_pdfplumber');
  check('TC-1: resolves to the registered vendor', result.vendor?.vendorId === vendorId);

  await runExtractionPipeline(documentId);
  const stmtRow = db.prepare(`SELECT COUNT(*) AS n FROM ${tableName} WHERE document_id = ?`).get(documentId);
  check('TC-1: a row lands in the vendor\'s extracted.stmt_<vendor_slug> table', stmtRow.n === 1);
}

// --- TC-2: document from a vendor not in registry routes to Claude-primary
// path without error, provisional vendor record created ---
{
  const text = makeStatementText({
    vendor: 'Brand_New_Vendor',
    total: '50.00',
    lines: [{ invoiceRef: 'INV-9', roNumber: null, amount: '50.00', date: '2026-07-05' }],
  });
  const documentId = registerTestDoc(text);
  const pdfBytes = makeTestPdf(text);
  const result = await identifyAndExtract(documentId, 'entity-1', pdfBytes);

  check('TC-2: routes to Claude-primary path for an unknown vendor', result.provider === 'claude_sonnet');
  check('TC-2: a provisional vendor record was created', !!result.vendor);
  const registryRow = db.prepare('SELECT extraction_route FROM extracted_vendor_registry WHERE vendor_id = ?').get(result.vendor.vendorId);
  check('TC-2: provisional vendor has no deterministic route yet', registryRow.extraction_route === null);
}

// --- TC-3: successful extraction writes one attempt row, arithmetic_pass=true,
// document.vendor_id/statement_period populated ---
{
  const text = makeStatementText({
    vendor: 'Keystone',
    period: '2026-07',
    total: '200.00',
    lines: [{ invoiceRef: 'INV-20', roNumber: null, amount: '200.00', date: '2026-07-10' }],
  });
  const documentId = registerTestDoc(text);
  await runExtractionPipeline(documentId);

  const attempts = db.prepare('SELECT * FROM extracted_extraction_attempt WHERE document_id = ?').all(documentId);
  check('TC-3: exactly one attempt row written on first success', attempts.length === 1);
  check('TC-3: arithmetic_pass is true', attempts[0].arithmetic_pass === 1);
  const doc = db.prepare('SELECT vendor_id, statement_period FROM extracted_document WHERE document_id = ?').get(documentId);
  check('TC-3: document.vendor_id populated', !!doc.vendor_id);
  check('TC-3: document.statement_period populated', doc.statement_period === '2026-07');
}

// --- TC-4 (S10): failed extraction (arithmetic mismatch) still writes an
// attempt row, arithmetic_pass=false, BEFORE any retry logic fires ---
{
  const text = makeStatementText({
    vendor: 'Mismatch_Vendor',
    total: '999.00', // deliberately wrong vs. the single 50.00 line
    lines: [{ invoiceRef: 'INV-30', roNumber: null, amount: '50.00', date: '2026-07-11' }],
  });
  const documentId = registerTestDoc(text);
  await runExtractionPipeline(documentId);

  const attempts = db.prepare('SELECT * FROM extracted_extraction_attempt WHERE document_id = ? ORDER BY attempt_no').all(documentId);
  check('TC-4: attempt row(s) written despite arithmetic mismatch', attempts.length > 0);
  check('TC-4 (S10): first attempt recorded arithmetic_pass=false', attempts[0].arithmetic_pass === 0);
}

// --- TC-5 (G1): modifying an existing attempt row via the application layer fails ---
{
  const text = makeStatementText({ vendor: 'ImmutableTest', total: '10.00', lines: [{ invoiceRef: 'INV-40', roNumber: null, amount: '10.00', date: '2026-07-12' }] });
  const documentId = registerTestDoc(text);
  await runExtractionPipeline(documentId);
  const attempt = db.prepare('SELECT attempt_id FROM extracted_extraction_attempt WHERE document_id = ?').get(documentId);
  try {
    db.prepare('UPDATE extracted_extraction_attempt SET attempt_no = 99 WHERE attempt_id = ?').run(attempt.attempt_id);
    check('TC-5 (G1): UPDATE on existing attempt row fails', false);
  } catch (e) {
    check(`TC-5 (G1): UPDATE on existing attempt row fails — ${e.message}`, /append-only/i.test(e.message));
  }
}

// --- TC-6 (S2): different document, same vendor/period/entity, is version-chained ---
{
  const vendorName = 'ChainVendor';
  const period = '2026-08';
  const textA = makeStatementText({ vendor: vendorName, period, total: '10.00', lines: [{ invoiceRef: 'A-1', roNumber: null, amount: '10.00', date: '2026-08-01' }] });
  const textB = makeStatementText({ vendor: vendorName, period, total: '20.00', lines: [{ invoiceRef: 'B-1', roNumber: null, amount: '20.00', date: '2026-08-02' }] });

  const docA = registerTestDoc(textA, 'entity-chain');
  await runExtractionPipeline(docA);
  const docB = registerTestDoc(textB, 'entity-chain');
  await runExtractionPipeline(docB);

  const rowA = db.prepare('SELECT previous_statement_id, is_latest_version FROM extracted_document WHERE document_id = ?').get(docA);
  const rowB = db.prepare('SELECT previous_statement_id, is_latest_version FROM extracted_document WHERE document_id = ?').get(docB);

  check('TC-6 (S2): older document is superseded (is_latest_version=0)', rowA.is_latest_version === 0);
  check('TC-6 (S2): newer document points at the older one', rowB.previous_statement_id === docA);
  check('TC-6 (S2): newer document is now latest', rowB.is_latest_version === 1);

  // --- TC-7: never both latest simultaneously ---
  const bothLatest = db
    .prepare(
      `SELECT COUNT(*) AS n FROM extracted_document
       WHERE document_id IN (?, ?) AND is_latest_version = 1`
    )
    .get(docA, docB).n;
  check('TC-7: never both documents show is_latest_version=1 simultaneously', bothLatest === 1);
}

await closeDb();

if (failures > 0) {
  console.error(`\n${failures} test case(s) FAILED.`);
  process.exit(1);
}
console.log('\nAll Task 3.1 test cases PASS.');
