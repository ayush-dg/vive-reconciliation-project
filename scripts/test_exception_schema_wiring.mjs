// Task 5.4 test cases — exception category enum + schema wiring, S5 + S8 (amended).
import crypto from 'node:crypto';
import { getSqliteDb, closeDb } from '../src/lib/db.ts';
import { runMigrations } from '../src/lib/migrate.ts';
import { registerDocument } from '../src/lib/documents.ts';
import { triggerMatchingForDocument } from '../src/lib/matchingInvocation.ts';
import { writeException } from '../src/lib/exceptionWriter.ts';
import { makeTestPdf } from './testPdfFixture.mjs';
import { ensureNetsuiteVendorBillFixtureTable, seedNetsuiteVendorBillRow } from './netsuiteVendorBillFixture.mjs';
import { ensureCccRepairOrderFixtureTable } from './cccRepairOrderFixture.mjs';

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
ensureCccRepairOrderFixtureTable();

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

// --- TC-1: every exception-producing path (Task 5.2's NOT_POSTED, Task 5.3's residual
// evidence riding along on it) writes a valid enum category. ---
{
  const documentId = registerTestDoc();
  insertSilverLine(documentId, 'INV-VALID-ENUM', 33);
  await triggerMatchingForDocument(documentId);

  const exception = db
    .prepare(`SELECT e.* FROM recon_exception e JOIN silver_statement_line sl ON sl.line_id = e.statement_line_id WHERE sl.document_id = ?`)
    .get(documentId);
  check('TC-1: the exception-producing path wrote a valid enum category', ['amount_mismatch', 'not_posted'].includes(exception?.category));
}

// --- TC-2 (S5): attempting to write an unrecognized category string is rejected, both at
// this module's own runtime check and at the DB's CHECK constraint. ---
{
  const documentId = registerTestDoc();
  const lineId = insertSilverLine(documentId, 'INV-BAD-ENUM', 5);

  let threwAtModule = false;
  try {
    writeException({ statementLineId: lineId, category: 'not_a_real_category', reasonCodes: [], evidence: {}, reference: null });
  } catch {
    threwAtModule = true;
  }
  check('TC-2 (S5): writeException rejects an unrecognized category', threwAtModule);

  let threwAtDb = false;
  try {
    db.prepare(
      `INSERT INTO recon_exception (exception_id, statement_line_id, category) VALUES (?, ?, 'not_a_real_category')`
    ).run(crypto.randomUUID(), lineId);
  } catch {
    threwAtDb = true;
  }
  check('TC-2 (S5): the DB\'s own CHECK constraint also rejects an unrecognized category', threwAtDb);
}

// --- TC-3: owner/aging_started_at/run_reference remain NULL after any exception is
// created — reserved for BCE, never populated by this build. ---
{
  const documentId = registerTestDoc();
  insertSilverLine(documentId, 'INV-BCE-RESERVED', 8);
  await triggerMatchingForDocument(documentId);

  const exception = db
    .prepare(`SELECT e.* FROM recon_exception e JOIN silver_statement_line sl ON sl.line_id = e.statement_line_id WHERE sl.document_id = ?`)
    .get(documentId);
  check('TC-3: owner is NULL', exception?.owner === null);
  check('TC-3: aging_started_at is NULL', exception?.aging_started_at === null);
  check('TC-3: run_reference is NULL', exception?.run_reference === null);
}

// --- TC-4 (S8 amended): a NOT_POSTED exception (Task 5.2's no-match path) carries
// non-NULL reference_run_id/reference_extracted_at/reference_source_system — captured
// from the reference table's own watermark (an unrelated row is seeded here so a
// watermark exists to capture; an entirely empty table's null-capture case is Task 5.2's
// own TC-10, not re-tested here). ---
{
  seedNetsuiteVendorBillRow(db, {
    transactionId: crypto.randomUUID(),
    billDocumentNumber: 'INV-UNRELATED-WATERMARK-SEED',
    amount: 1,
    runId: 'run-watermark-seed',
    extractedAt: '2026-08-27T00:00:00Z',
  });

  const documentId = registerTestDoc();
  insertSilverLine(documentId, 'INV-NOTPOSTED-REF', 15);
  await triggerMatchingForDocument(documentId);

  const exception = db
    .prepare(`SELECT e.* FROM recon_exception e JOIN silver_statement_line sl ON sl.line_id = e.statement_line_id WHERE sl.document_id = ? AND e.category = 'not_posted'`)
    .get(documentId);
  check('TC-4 (S8): a not_posted exception carries non-NULL reference columns', !!exception && exception.reference_run_id !== null && exception.reference_extracted_at !== null && exception.reference_source_system !== null);
}

// --- TC-5: an exception that never touched reference data leaves those 3 columns NULL.
// EXECUTION_PLAN.md's own literal test case names an "arithmetic-mismatch exception
// (Task 3.2)" for this — but that scenario cannot occur in this build's actual
// architecture: Task 3.2's validation gate blocks a line from ever reaching Silver at all
// when arithmetic fails, so it can never acquire a statement_line_id to attach a
// recon.exception row to (recon_exception.statement_line_id has a NOT NULL FK to
// silver_statement_line). Flagged as a planning-doc inconsistency (Out of Scope
// Observations, sessions/S05_SESSION_LOG.md), not invented around.
//
// This test instead drives the REAL, reachable NULL-reference case end-to-end: a
// not_posted exception produced while bronze_netsuite_vendorbill is genuinely empty
// (findLatestReferenceWatermark() has nothing at all to capture — Task 5.2's own TC-10
// proves this returns null at the matchStatementLine() level; this test goes one step
// further and confirms it actually persists as NULL columns in recon_exception through
// the real pipeline, which no test previously did — an earlier draft of this test instead
// called writeException() directly with an amount_mismatch+null pairing that
// deterministicMatching.ts's AMOUNT_MISMATCH branch can never actually produce, per
// challenge review). Temporarily empties the shared netsuite fixture table (restored
// after), same technique as Task 5.2's own TC-10. ---
{
  db.exec('CREATE TEMPORARY TABLE bronze_netsuite_vendorbill_backup_5_4 AS SELECT * FROM bronze_netsuite_vendorbill');
  db.exec('DELETE FROM bronze_netsuite_vendorbill');
  try {
    const documentId = registerTestDoc();
    insertSilverLine(documentId, 'INV-NO-REFERENCE-DATA', 1);
    await triggerMatchingForDocument(documentId);

    const exception = db
      .prepare(`SELECT e.* FROM recon_exception e JOIN silver_statement_line sl ON sl.line_id = e.statement_line_id WHERE sl.document_id = ?`)
      .get(documentId);
    check('TC-5: a not_posted exception against a genuinely empty reference table leaves all 3 reference columns NULL', !!exception && exception.reference_run_id === null && exception.reference_extracted_at === null && exception.reference_source_system === null);
  } finally {
    db.exec('INSERT INTO bronze_netsuite_vendorbill SELECT * FROM bronze_netsuite_vendorbill_backup_5_4');
    db.exec('DROP TABLE bronze_netsuite_vendorbill_backup_5_4');
  }
}

// --- TC-7 (challenge-review addition): reason_codes — named explicitly by D-K's
// structured result contract and this task's own CC prompt ("sourcing
// category/reason_codes/evidence directly... rather than re-deriving them") — is actually
// persisted, not silently dropped after being used once to derive category. ---
{
  const documentId = registerTestDoc();
  insertSilverLine(documentId, 'INV-REASON-CODES', 44);
  await triggerMatchingForDocument(documentId);

  const exception = db
    .prepare(`SELECT e.* FROM recon_exception e JOIN silver_statement_line sl ON sl.line_id = e.statement_line_id WHERE sl.document_id = ?`)
    .get(documentId);
  let reasonCodes = null;
  try {
    reasonCodes = JSON.parse(exception.reason_codes);
  } catch {
    /* leave null */
  }
  check('TC-7: reason_codes is persisted as a parseable array', Array.isArray(reasonCodes));
  check('TC-7: reason_codes includes the deterministic stage\'s own reason (NOT_POSTED)', reasonCodes?.includes('NOT_POSTED'));
}

// --- TC-6: evidence is persisted as valid, parseable JSON on every exception row. ---
{
  const documentId = registerTestDoc();
  insertSilverLine(documentId, 'INV-EVIDENCE-JSON', 27);
  await triggerMatchingForDocument(documentId);

  const exception = db
    .prepare(`SELECT e.* FROM recon_exception e JOIN silver_statement_line sl ON sl.line_id = e.statement_line_id WHERE sl.document_id = ?`)
    .get(documentId);
  let parsed = null;
  try {
    parsed = JSON.parse(exception.evidence);
  } catch {
    /* leave null */
  }
  check('TC-6: evidence is persisted as valid, parseable JSON', parsed !== null && typeof parsed === 'object');
}

await closeDb();

if (failures > 0) {
  console.error(`\n${failures} test case(s) FAILED.`);
  process.exit(1);
}
console.log('\nAll Task 5.4 test cases PASS.');
