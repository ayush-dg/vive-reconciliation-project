// Task 5.2 test cases — deterministic SQL-based matching, S8 amended.
import crypto from 'node:crypto';
import { getSqliteDb, closeDb } from '../src/lib/db.ts';
import { runMigrations } from '../src/lib/migrate.ts';
import { registerDocument } from '../src/lib/documents.ts';
import { triggerMatchingForDocument } from '../src/lib/matchingInvocation.ts';
import { matchStatementLine, writeMatch } from '../src/lib/deterministicMatching.ts';
import { makeTestPdf } from './testPdfFixture.mjs';
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

function registerTestDoc() {
  const bytes = makeTestPdf(`irrelevant-${crypto.randomUUID()}`);
  const { document } = registerDocument(bytes, 'entity-1');
  return document.documentId;
}

function insertSilverLine(documentId, invoiceRef, amount) {
  const vendorId = crypto.randomUUID();
  db.prepare(
    `INSERT INTO extracted_vendor_registry (vendor_id, vendor_slug, table_name, extraction_route) VALUES (?, ?, ?, NULL)`
  ).run(vendorId, `test_vendor_${vendorId.slice(0, 8)}`, `extracted_stmt_test_${vendorId.slice(0, 8)}`);
  const lineId = crypto.randomUUID();
  db.prepare(
    `INSERT INTO silver_statement_line (line_id, document_id, vendor_id, amount, invoice_ref, normalized_invoice_ref, normalization_version)
     VALUES (?, ?, ?, ?, ?, ?, 'v1')`
  ).run(lineId, documentId, vendorId, amount, invoiceRef, invoiceRef.toUpperCase());
  return lineId;
}

// --- TC-1: a StatementLine with a matching NetSuite Bill document number produces a
// Match record, with the 3 reference columns populated from the matched row. ---
{
  const documentId = registerTestDoc();
  insertSilverLine(documentId, 'INV-100', 50);
  seedNetsuiteVendorBillRow(db, {
    transactionId: crypto.randomUUID(),
    billDocumentNumber: 'INV-100',
    amount: 50,
    runId: 'run-001',
    extractedAt: '2026-08-27T00:00:00Z',
  });

  await triggerMatchingForDocument(documentId);

  const match = db
    .prepare(`SELECT m.* FROM recon_match m JOIN silver_statement_line sl ON sl.line_id = m.statement_line_id WHERE sl.document_id = ?`)
    .get(documentId);
  check('TC-1: a Match record is produced', !!match);
  check('TC-1: reference_run_id populated from the matched NetSuite row', match?.reference_run_id === 'run-001');
  check('TC-1: reference_extracted_at populated', match?.reference_extracted_at === '2026-08-27T00:00:00Z');
  check('TC-1: reference_source_system populated', match?.reference_source_system === 'netsuite');
}

// --- TC-2: a StatementLine with no corresponding NetSuite record produces an Exception
// (category NOT_POSTED), with reference columns populated from the reference table's own
// current watermark (what state of NetSuite data was checked), per this task's own Scope
// Decision (see sessions/S05_VERIFICATION_RECORD.md). ---
{
  const documentId = registerTestDoc();
  insertSilverLine(documentId, 'INV-NOTFOUND', 75);

  await triggerMatchingForDocument(documentId);

  const exception = db
    .prepare(`SELECT e.* FROM recon_exception e JOIN silver_statement_line sl ON sl.line_id = e.statement_line_id WHERE sl.document_id = ?`)
    .get(documentId);
  check('TC-2: an Exception is produced for an unmatched invoice', !!exception);
  check('TC-2: category is not_posted', exception?.category === 'not_posted');
  check('TC-2: reference columns are populated (the reference table\'s own watermark, even though nothing matched)', !!exception?.reference_run_id);
}

// --- TC-3 (S8, amended): attempting to write a Match with a null reference column is
// rejected — the schema-level NOT NULL constraint on recon.match. ---
{
  const documentId = registerTestDoc();
  const lineId = insertSilverLine(documentId, 'INV-NULLCHECK', 10);
  let threw = false;
  try {
    db.prepare(
      `INSERT INTO recon_match (match_id, statement_line_id, reference_run_id, reference_extracted_at, reference_source_system)
       VALUES (?, ?, NULL, 'x', 'netsuite')`
    ).run(crypto.randomUUID(), lineId);
  } catch {
    threw = true;
  }
  check('TC-3 (S8): a Match with a NULL reference column is rejected', threw);
}

// --- TC-4: matching logic never makes a live NetSuite/CCC API call — structural check
// (deterministicMatching.ts contains no fetch/http import, only local SQL reads). ---
{
  const fs = await import('node:fs');
  const source = fs.readFileSync('src/lib/deterministicMatching.ts', 'utf8');
  check('TC-4: deterministicMatching.ts makes no live HTTP/fetch call', !/\bfetch\(|node-fetch|axios/.test(source));
}

// --- TC-5: an amount mismatch (doc number found, amounts disagree) is unmatched with
// reason AMOUNT_MISMATCH — this task's own extension beyond the 2 spec'd cases, since
// 'amount_mismatch' is a real, schema-enforced category with no other code path to
// produce it (see Scope Decision). ---
{
  const line = { normalizedInvoiceRef: 'INV-200', amount: 100 };
  const documentId = registerTestDoc();
  seedNetsuiteVendorBillRow(db, {
    transactionId: crypto.randomUUID(),
    billDocumentNumber: 'INV-200',
    amount: 999,
    runId: 'run-002',
    extractedAt: '2026-08-27T00:00:00Z',
  });
  const outcome = await matchStatementLine(line);
  check('TC-5: amount mismatch is unmatched, not silently accepted', outcome.status === 'unmatched');
  check('TC-5: reason code is AMOUNT_MISMATCH', outcome.reasonCodes.includes('AMOUNT_MISMATCH'));
  check('TC-5: reference is still captured for an amount-mismatch outcome', !!outcome.reference);
  void documentId;
}

// --- TC-6: writeMatch's own contract — throws if given a match whose statement_line_id
// doesn't exist (FK enforced), rather than silently inserting an orphaned row. ---
{
  let threw = false;
  try {
    writeMatch('00000000-0000-0000-0000-000000000000', { runId: 'x', extractedAt: 'x', sourceSystem: 'x' });
  } catch {
    threw = true;
  }
  check('TC-6: writeMatch rejects a nonexistent statement_line_id (FK enforced)', threw);
}

// --- TC-7 (challenge-review addition): a real-world casing/whitespace difference in the
// NetSuite bill_document_number must not produce a false NOT_POSTED — the comparison
// normalizes both sides. ---
{
  const documentId = registerTestDoc();
  insertSilverLine(documentId, 'INV-CASE-1', 20);
  seedNetsuiteVendorBillRow(db, {
    transactionId: crypto.randomUUID(),
    billDocumentNumber: '  inv-case-1  ', // lowercase + padding, as a real source system might store it
    amount: 20,
    runId: 'run-case',
    extractedAt: '2026-08-27T00:00:00Z',
  });

  await triggerMatchingForDocument(documentId);

  const match = db
    .prepare(`SELECT m.* FROM recon_match m JOIN silver_statement_line sl ON sl.line_id = m.statement_line_id WHERE sl.document_id = ?`)
    .get(documentId);
  check('TC-7: a case/whitespace-differing bill_document_number still matches', !!match);
}

// --- TC-8 (challenge-review addition): duplicate bill_document_number rows (structurally
// possible — no uniqueness constraint on this column) resolve deterministically to the
// most-recently-extracted row, not an arbitrary one. ---
{
  const older = { transactionId: crypto.randomUUID(), billDocumentNumber: 'INV-DUP', amount: 30, runId: 'run-old', extractedAt: '2026-08-01T00:00:00Z' };
  const newer = { transactionId: crypto.randomUUID(), billDocumentNumber: 'INV-DUP', amount: 30, runId: 'run-new', extractedAt: '2026-08-27T00:00:00Z' };
  seedNetsuiteVendorBillRow(db, older);
  seedNetsuiteVendorBillRow(db, newer);

  const outcome = await matchStatementLine({ normalizedInvoiceRef: 'INV-DUP', amount: 30 });
  check('TC-8: duplicate doc numbers resolve deterministically to the most-recently-extracted row', outcome.reference?.runId === 'run-new');
}

// --- TC-9 (challenge-review addition): the AMOUNT_MISMATCH outcome, driven end-to-end
// through runMatchingForDocument (not just unit-tested at matchStatementLine), lands as a
// recon.exception row with category=amount_mismatch and reference columns populated. ---
{
  const documentId = registerTestDoc();
  insertSilverLine(documentId, 'INV-E2E-MISMATCH', 100);
  seedNetsuiteVendorBillRow(db, {
    transactionId: crypto.randomUUID(),
    billDocumentNumber: 'INV-E2E-MISMATCH',
    amount: 999,
    runId: 'run-e2e-mismatch',
    extractedAt: '2026-08-27T00:00:00Z',
  });

  await triggerMatchingForDocument(documentId);

  const exception = db
    .prepare(`SELECT e.* FROM recon_exception e JOIN silver_statement_line sl ON sl.line_id = e.statement_line_id WHERE sl.document_id = ?`)
    .get(documentId);
  check('TC-9: an end-to-end amount mismatch lands as an exception, not a match', !!exception);
  check('TC-9: category is amount_mismatch', exception?.category === 'amount_mismatch');
  check('TC-9: reference columns populated from the mismatched row', exception?.reference_run_id === 'run-e2e-mismatch');
}

// --- TC-10 (challenge-review addition): NOT_POSTED against a genuinely EMPTY reference
// table (not merely "no row for this doc number") leaves all 3 reference columns NULL —
// the true zero-rows watermark branch, never exercised by TC-2 since a fixture row was
// already seeded by then. Uses a fresh in-memory-only check against a temporary empty copy
// of the table rather than clearing the shared fixture (which later test cases still rely
// on). ---
{
  db.exec('CREATE TEMPORARY TABLE bronze_netsuite_vendorbill_backup AS SELECT * FROM bronze_netsuite_vendorbill');
  db.exec('DELETE FROM bronze_netsuite_vendorbill');
  try {
    const outcome = await matchStatementLine({ normalizedInvoiceRef: 'INV-EMPTY-TABLE', amount: 5 });
    check('TC-10: NOT_POSTED against a genuinely empty reference table', outcome.status === 'unmatched' && outcome.reasonCodes.includes('NOT_POSTED'));
    check('TC-10: reference is null (nothing at all to capture), not a fabricated watermark', outcome.reference === null);
  } finally {
    db.exec('INSERT INTO bronze_netsuite_vendorbill SELECT * FROM bronze_netsuite_vendorbill_backup');
    db.exec('DROP TABLE bronze_netsuite_vendorbill_backup');
  }
}

await closeDb();

if (failures > 0) {
  console.error(`\n${failures} test case(s) FAILED.`);
  process.exit(1);
}
console.log('\nAll Task 5.2 test cases PASS.');
