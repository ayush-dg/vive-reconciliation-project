// Session 5 integration check — end-to-end round trip through the REAL public entry
// points, composing Session 3's extraction pipeline and Session 5's matching pipeline for
// the first time: registerDocument -> triggerExtraction -> Silver -> triggerMatchingForDocument
// -> Match/Exception. Exercises both sessions' G5 locks and both sessions' real (non-mock)
// SQL logic together, not just each session's own isolated task scripts.
import { getSqliteDb, closeDb } from '../src/lib/db.ts';
import { runMigrations } from '../src/lib/migrate.ts';
import { registerDocument } from '../src/lib/documents.ts';
import { triggerExtraction } from '../src/lib/extraction.ts';
import { triggerMatchingForDocument, runScheduledMatchingBatch } from '../src/lib/matchingInvocation.ts';
import { computeDocumentStatus } from '../src/lib/documentStatus.ts';
import { makeTestPdf, makeStatementText } from './testPdfFixture.mjs';
import { ensureNetsuiteVendorBillFixtureTable, seedNetsuiteVendorBillRow } from './netsuiteVendorBillFixture.mjs';

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
ensureNetsuiteVendorBillFixtureTable();

// --- Full round trip: a real vendor statement PDF, extracted via Session 3's real
// pipeline, then matched via Session 5's real pipeline against a seeded NetSuite row. ---
{
  const text = makeStatementText({
    vendor: 'E2E_Matching_Vendor',
    period: '2026-08',
    total: '300.00',
    lines: [{ invoiceRef: 'MATCH-E2E-1', roNumber: null, amount: '300.00', date: '2026-08-15' }],
  });
  const bytes = makeTestPdf(text);
  const { document } = registerDocument(bytes, 'e2e-entity');

  const extractResult = await triggerExtraction(document.documentId);
  check('Extraction succeeds (Session 3\'s real pipeline)', extractResult.ok === true);

  seedNetsuiteVendorBillRow(db, {
    transactionId: 'e2e-txn-1',
    billDocumentNumber: 'MATCH-E2E-1',
    amount: 300,
    runId: 'e2e-run-1',
    extractedAt: '2026-08-27T00:00:00Z',
  });

  const matchResult = await triggerMatchingForDocument(document.documentId);
  check('Matching succeeds (Session 5\'s real pipeline)', matchResult.ok === true);

  // A sequential re-trigger (after the first fully completed and released its lock) is
  // NOT rejected — matching is a repeatable operation (Task 5.1's own TC-6/TC-7 already
  // establish this), unlike extraction's one-way lock. It succeeds harmlessly here
  // because there are no eligible lines left to (re)process, not because G5 blocked it.
  // True concurrent-invocation exclusion is Task 5.1's own dedicated G5 test coverage.
  const secondMatch = await triggerMatchingForDocument(document.documentId);
  check('A sequential re-trigger after full completion succeeds harmlessly (matching is repeatable)', secondMatch.ok === true);
  const matchCountAfterSecondTrigger = db
    .prepare(`SELECT COUNT(*) AS n FROM recon_match m JOIN silver_statement_line sl ON sl.line_id = m.statement_line_id WHERE sl.document_id = ?`)
    .get(document.documentId);
  check('The re-trigger did not create a duplicate Match row', matchCountAfterSecondTrigger.n === 1);

  const match = db
    .prepare(`SELECT m.* FROM recon_match m JOIN silver_statement_line sl ON sl.line_id = m.statement_line_id WHERE sl.document_id = ?`)
    .get(document.documentId);
  check('A real Match record was produced end-to-end', !!match);
  check('The Match carries S8\'s reference capture', match?.reference_run_id === 'e2e-run-1');

  const status = computeDocumentStatus(document.documentId);
  check('Document status reflects Reconciled after a successful end-to-end match', status.badge === 'Reconciled');
}

// --- Scheduled batch path: an unmatched, extracted document (no NetSuite row seeded for
// it) is picked up and produces a NOT_POSTED exception, not silently skipped. ---
{
  const text = makeStatementText({
    vendor: 'E2E_Batch_Vendor',
    period: '2026-08',
    total: '45.00',
    lines: [{ invoiceRef: 'BATCH-E2E-1', roNumber: null, amount: '45.00', date: '2026-08-16' }],
  });
  const bytes = makeTestPdf(text);
  const { document } = registerDocument(bytes, 'e2e-entity');
  await triggerExtraction(document.documentId);

  const batchResult = await runScheduledMatchingBatch();
  check('The scheduled batch picks up the unmatched, extracted document', batchResult.processed.includes(document.documentId));

  const exception = db
    .prepare(`SELECT e.* FROM recon_exception e JOIN silver_statement_line sl ON sl.line_id = e.statement_line_id WHERE sl.document_id = ?`)
    .get(document.documentId);
  check('A NOT_POSTED exception is produced via the scheduled batch path', exception?.category === 'not_posted');
}

await closeDb();

if (failures > 0) {
  console.error(`\n${failures} check(s) FAILED.`);
  process.exit(1);
}
console.log('\nEnd-to-end matching service round trip: PASS.');
