// Task 3.6 test cases — extracted -> silver.statement_line normalization.
import { getSqliteDb, closeDb } from '../src/lib/db.ts';
import { runMigrations } from '../src/lib/migrate.ts';
import { registerDocument } from '../src/lib/documents.ts';
import { runExtractionPipeline } from '../src/lib/extractionPipeline.ts';
import { normalizeToSilver, NORMALIZATION_VERSION } from '../src/lib/silverNormalization.ts';
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

// --- TC-1: a document that passes validation produces one or more silver.statement_line rows. ---
{
  const text = makeStatementText({
    vendor: 'Silver_Pass_Vendor',
    total: '60.00',
    lines: [
      { invoiceRef: 'INV-1', roNumber: null, amount: '25.00', date: '2026-07-01' },
      { invoiceRef: 'INV-2', roNumber: null, amount: '35.00', date: '2026-07-02' },
    ],
  });
  const documentId = registerTestDoc(text);
  await runExtractionPipeline(documentId);

  const rows = db.prepare('SELECT * FROM silver_statement_line WHERE document_id = ?').all(documentId);
  check('TC-1: two lines produce two silver.statement_line rows', rows.length === 2);
  check('TC-1: vendor_id is populated on the produced rows', rows.every((r) => !!r.vendor_id));
}

// --- TC-2: a document that fails validation produces zero silver.statement_line rows. ---
{
  const text = makeStatementText({
    vendor: 'Silver_Fail_Vendor',
    total: '999.00', // deliberately wrong vs. the single 10.00 line
    lines: [{ invoiceRef: 'INV-3', roNumber: null, amount: '10.00', date: '2026-07-03' }],
  });
  const documentId = registerTestDoc(text);
  await runExtractionPipeline(documentId);

  const rows = db.prepare('SELECT COUNT(*) AS n FROM silver_statement_line WHERE document_id = ?').get(documentId);
  check('TC-2: validation failure produces zero silver.statement_line rows', rows.n === 0);
}

// --- TC-3: every produced row is tagged with the normalization logic version. ---
{
  const text = makeStatementText({
    vendor: 'Silver_Version_Vendor',
    total: '12.00',
    lines: [{ invoiceRef: 'INV-4', roNumber: null, amount: '12.00', date: '2026-07-04' }],
  });
  const documentId = registerTestDoc(text);
  await runExtractionPipeline(documentId);

  const rows = db.prepare('SELECT normalization_version FROM silver_statement_line WHERE document_id = ?').all(documentId);
  check('TC-3: produced row(s) exist to check', rows.length > 0);
  check('TC-3 (S6): every row tagged with the current normalization version', rows.every((r) => r.normalization_version === NORMALIZATION_VERSION));
}

// --- TC-4 (S11): silver.statement_line.amount is immutable once written. ---
{
  const text = makeStatementText({
    vendor: 'Silver_Immutable_Vendor',
    total: '18.00',
    lines: [{ invoiceRef: 'INV-5', roNumber: null, amount: '18.00', date: '2026-07-05' }],
  });
  const documentId = registerTestDoc(text);
  await runExtractionPipeline(documentId);

  const row = db.prepare('SELECT line_id FROM silver_statement_line WHERE document_id = ?').get(documentId);
  try {
    db.prepare('UPDATE silver_statement_line SET amount = 999 WHERE line_id = ?').run(row.line_id);
    check('TC-4 (S11): UPDATE on amount fails', false);
  } catch (e) {
    check(`TC-4 (S11): UPDATE on amount fails — ${e.message}`, /immutable/i.test(e.message));
  }
}

// --- TC-5: a blank-amount (credit/payment) line normalizes to 0, not left NULL (the amount
// column is NOT NULL) — direct unit test of normalizeToSilver's own mapping rule. ---
{
  const documentId = registerTestDoc(
    makeStatementText({ vendor: 'Silver_Credit_Vendor', total: '5.00', lines: [{ invoiceRef: 'INV-6', roNumber: null, amount: '5.00', date: '2026-07-06' }] })
  );
  // A throwaway registry row, just to satisfy silver_statement_line's vendor_id FK —
  // this test targets normalizeToSilver's own mapping rule directly, not routing.
  const vendorId = 'silver-unit-test-vendor';
  db.prepare(
    `INSERT OR IGNORE INTO extracted_vendor_registry (vendor_id, vendor_slug, table_name, extraction_route) VALUES (?, 'silver_unit_test_vendor', 'extracted_stmt_silver_unit_test_vendor', NULL)`
  ).run(vendorId);

  normalizeToSilver(documentId, vendorId, {
    vendorNameGuess: 'Silver Credit Vendor',
    statementPeriod: null,
    statementTotal: 0,
    lines: [{ invoiceRef: 'CREDIT-1', roNumber: null, amount: null, date: '2026-07-07' }],
  });

  const row = db.prepare('SELECT amount FROM silver_statement_line WHERE document_id = ? AND invoice_ref = ?').get(documentId, 'CREDIT-1');
  check('TC-5: a blank-amount credit line normalizes to 0, not NULL', row.amount === 0);
}

// --- TC-6 (challenge-review addition): re-invoking runExtractionPipeline directly on a
// document that already succeeded must never reprocess it — no duplicate attempt row, no
// duplicate silver_statement_line row. (extraction.ts's G5 lock already prevents this via
// the HTTP endpoint, since status stays 'processing' forever after completion — but nothing
// stopped a direct call to runExtractionPipeline itself, e.g. a future batch-reprocessing
// caller, from re-running an already-succeeded document.) ---
{
  const text = makeStatementText({
    vendor: 'Silver_Idempotent_Vendor',
    total: '22.00',
    lines: [{ invoiceRef: 'INV-7', roNumber: null, amount: '22.00', date: '2026-07-08' }],
  });
  const documentId = registerTestDoc(text);
  await runExtractionPipeline(documentId);
  await runExtractionPipeline(documentId); // direct re-invocation, bypassing extraction.ts's lock

  const attempts = db.prepare('SELECT COUNT(*) AS n FROM extracted_extraction_attempt WHERE document_id = ?').get(documentId);
  const silverRows = db.prepare('SELECT COUNT(*) AS n FROM silver_statement_line WHERE document_id = ?').get(documentId);
  check('TC-6: re-invoking the pipeline on an already-succeeded document adds no 2nd attempt row', attempts.n === 1);
  check('TC-6: re-invoking the pipeline on an already-succeeded document adds no duplicate silver row', silverRows.n === 1);
}

// --- TC-7 (challenge-review addition): if Silver normalization fails unexpectedly after
// validation already passed (e.g. a downstream write/constraint failure), the failure must
// surface as a clear, attributable error — not vanish as an unhandled rejection while an
// attempt row already committed as "passed" sits with no diagnostic trail. Forced
// deterministically via a one-off trigger that aborts any silver_statement_line INSERT for
// a specific marker invoice_ref, simulating an unexpected downstream write failure. ---
{
  // A CREATE TEMP TRIGGER here would bind to this script's own connection
  // object, which — despite pointing at the same file — is a materially
  // different SQLite connection from the one silverNormalization.ts's own
  // `./db`-relative import resolves internally; TEMP schema objects are
  // connection-local and would silently never fire on the real insert. A
  // persistent trigger (dropped at the end) is visible to any connection.
  db.exec(`
    CREATE TRIGGER IF NOT EXISTS force_silver_write_failure
    BEFORE INSERT ON silver_statement_line
    WHEN NEW.invoice_ref = 'FORCE-SILVER-CRASH'
    BEGIN
      SELECT RAISE(ABORT, 'forced test failure — simulated downstream write failure');
    END;
  `);

  const text = makeStatementText({
    vendor: 'Silver_Crash_Vendor',
    total: '7.00',
    lines: [{ invoiceRef: 'FORCE-SILVER-CRASH', roNumber: null, amount: '7.00', date: '2026-07-09' }],
  });
  const documentId = registerTestDoc(text);

  let thrown = null;
  try {
    await runExtractionPipeline(documentId);
  } catch (err) {
    thrown = err;
  }
  check('TC-7: an unexpected Silver-normalization failure surfaces as a thrown error, not silently vanishing', thrown instanceof Error);
  check('TC-7: the thrown error carries clear diagnostic context', !!thrown && thrown.message.includes('Silver normalization failed'));

  const attempts = db.prepare('SELECT arithmetic_pass, structural_pass FROM extracted_extraction_attempt WHERE document_id = ?').all(documentId);
  check('TC-7: the attempt row still correctly recorded that extraction validation passed (G1 — not rewritten)', attempts.length === 1 && attempts[0].arithmetic_pass === 1 && attempts[0].structural_pass === 1);

  const silverRows = db.prepare('SELECT COUNT(*) AS n FROM silver_statement_line WHERE document_id = ?').get(documentId);
  check('TC-7: the aborted transaction leaves zero partial silver rows', silverRows.n === 0);

  db.exec('DROP TRIGGER IF EXISTS force_silver_write_failure');
}

await closeDb();

if (failures > 0) {
  console.error(`\n${failures} test case(s) FAILED.`);
  process.exit(1);
}
console.log('\nAll Task 3.6 test cases PASS.');
