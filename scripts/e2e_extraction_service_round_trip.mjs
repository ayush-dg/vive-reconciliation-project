// Session 3 integration check — end-to-end round trip through the REAL public entry
// points (not runExtractionPipeline directly): registerDocument -> triggerExtraction (the
// same function Task 2.4's API route calls, exercising G5's lock) -> Silver -> status
// badge -> extraction-method summary. Confirms the six tasks work together as a real
// Extract click would exercise them, not just as isolated units.
import { getSqliteDb, closeDb } from '../src/lib/db.ts';
import { runMigrations } from '../src/lib/migrate.ts';
import { registerDocument } from '../src/lib/documents.ts';
import { triggerExtraction } from '../src/lib/extraction.ts';
import { computeDocumentStatus } from '../src/lib/documentStatus.ts';
import { getExtractionMethodSummary } from '../src/lib/extractionMethodSummary.ts';
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

const text = makeStatementText({
  vendor: 'E2E_Smoke_Vendor',
  period: '2026-08',
  total: '150.00',
  lines: [
    { invoiceRef: 'E2E-1', roNumber: null, amount: '100.00', date: '2026-08-01' },
    { invoiceRef: 'E2E-2', roNumber: null, amount: '50.00', date: '2026-08-02' },
  ],
});
const bytes = makeTestPdf(text);
const { document, duplicate } = registerDocument(bytes, 'e2e-entity');
check('Document registers as new, not a duplicate', duplicate === false);

const result = await triggerExtraction(document.documentId);
check('Extract trigger succeeds (G5 lock acquired)', result.ok === true);

const second = await triggerExtraction(document.documentId);
check('A second, concurrent-style Extract trigger is rejected, not double-processed (G5)', second.ok === false && second.reason === 'already_processing');

const attempts = db.prepare('SELECT * FROM extracted_extraction_attempt WHERE document_id = ?').all(document.documentId);
check('Exactly one extraction attempt was recorded', attempts.length === 1);
check('The attempt passed both structural and arithmetic validation', attempts[0].arithmetic_pass === 1 && attempts[0].structural_pass === 1);

const silverRows = db.prepare('SELECT * FROM silver_statement_line WHERE document_id = ? ORDER BY invoice_ref').all(document.documentId);
check('Both statement lines were normalized to Silver', silverRows.length === 2);
check('Every Silver row carries the normalization_version tag (S6)', silverRows.every((r) => !!r.normalization_version));

const status = computeDocumentStatus(document.documentId);
check('Document status reads as Processing (matching-eligible), not stuck/failed', status.badge === 'Processing');

const summary = getExtractionMethodSummary(document.documentId);
check('Extraction-method summary reflects the real provider used', summary.claude_sonnet === 1);

await closeDb();

if (failures > 0) {
  console.error(`\n${failures} check(s) FAILED.`);
  process.exit(1);
}
console.log('\nEnd-to-end extraction service round trip: PASS.');
