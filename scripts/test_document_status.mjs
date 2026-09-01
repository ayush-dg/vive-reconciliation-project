// Task 2.3 test cases — status badge computation. No extraction service
// exists yet (Session 3) — extraction_attempt rows are inserted directly to
// synthesize each scenario, per this task's own scope ("expose this as a
// queryable field/view for that later task to consume").
import crypto from 'node:crypto';
import { getSqliteDb, closeDb } from '../src/lib/db.ts';
import { runMigrations } from '../src/lib/migrate.ts';
import { registerDocument } from '../src/lib/documents.ts';
import { computeDocumentStatus } from '../src/lib/documentStatus.ts';

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

function newDoc() {
  const { document } = registerDocument(Buffer.from(`doc-${crypto.randomUUID()}`), 'vive-holdings');
  return document.documentId;
}

function insertAttempt(documentId, attemptNo, { arithmeticPass = null, structuralPass = null } = {}) {
  db.prepare(
    `INSERT INTO extracted_extraction_attempt (attempt_id, document_id, attempt_no, arithmetic_pass, structural_pass)
     VALUES (?, ?, ?, ?, ?)`
  ).run(crypto.randomUUID(), documentId, attemptNo, arithmeticPass, structuralPass);
}

// --- TC-1: zero attempts -> "Processing" ---
const docZero = newDoc();
const statusZero = computeDocumentStatus(docZero);
check('TC-1: zero attempts -> Processing', statusZero.label === 'Processing');

// --- Bonus: an attempt in progress (not yet validated) -> still "Processing" ---
const docInProgress = newDoc();
insertAttempt(docInProgress, 1); // both pass fields NULL
const statusInProgress = computeDocumentStatus(docInProgress);
check('Bonus: attempt in progress (unvalidated) -> Processing', statusInProgress.label === 'Processing');

// --- TC-2: one failed attempt -> "Retrying (1/2)" ---
const docOneFail = newDoc();
insertAttempt(docOneFail, 1, { arithmeticPass: 0, structuralPass: 1 });
const statusOneFail = computeDocumentStatus(docOneFail);
check('TC-2: one failed attempt -> Retrying (1/2)', statusOneFail.label === 'Retrying (1/2)');

// --- TC-3: two failed attempts -> "Failed — see Exceptions" (S7 bound) ---
const docTwoFail = newDoc();
insertAttempt(docTwoFail, 1, { arithmeticPass: 0, structuralPass: 1 });
insertAttempt(docTwoFail, 2, { arithmeticPass: 1, structuralPass: 0 });
const statusTwoFail = computeDocumentStatus(docTwoFail);
check('TC-3: two failed attempts -> Failed — see Exceptions', statusTwoFail.label === 'Failed — see Exceptions');

// --- Bonus: a successful attempt (both pass) with no match yet -> "Extracted" ---
// (matching hasn't run — a passed validation gate alone isn't "Reconciled"; distinct
// from "Processing" as of 2026-08-31 — see documentStatus.ts's top comment)
const docPassedNoMatch = newDoc();
insertAttempt(docPassedNoMatch, 1, { arithmeticPass: 1, structuralPass: 1 });
const statusPassedNoMatch = computeDocumentStatus(docPassedNoMatch);
check('Bonus: validation passed but no match yet -> Extracted (not Processing, not Reconciled)', statusPassedNoMatch.label === 'Extracted');

function makeVendor() {
  const vendorId = crypto.randomUUID();
  db.prepare(
    `INSERT INTO extracted_vendor_registry (vendor_id, vendor_slug, table_name) VALUES (?, ?, ?)`
  ).run(vendorId, `test_vendor_${vendorId.slice(0, 8)}`, `extracted_stmt_test_${vendorId.slice(0, 8)}`);
  return vendorId;
}

function reconcile(documentId) {
  const vendorId = makeVendor();
  db.prepare(`UPDATE extracted_document SET vendor_id = ? WHERE document_id = ?`).run(vendorId, documentId);
  const lineId = crypto.randomUUID();
  db.prepare(
    `INSERT INTO silver_statement_line (line_id, document_id, vendor_id, amount) VALUES (?, ?, ?, 100.00)`
  ).run(lineId, documentId, vendorId);
  // snapshot_version was replaced by reference_run_id/reference_extracted_at/
  // reference_source_system in migration 005 (Session 5, S8 amended) — this script
  // predates that change and was never updated until Session 6 re-ran it.
  db.prepare(
    `INSERT INTO recon_match (match_id, statement_line_id, reference_run_id, reference_extracted_at, reference_source_system)
     VALUES (?, ?, 'test-run-1', '2026-08-27T00:00:00Z', 'netsuite')`
  ).run(crypto.randomUUID(), lineId);
  return lineId;
}

// --- Bonus: a recon.match exists -> "Reconciled" (forward-compat, no live pipeline) ---
const docReconciled = newDoc();
reconcile(docReconciled);
const statusReconciled = computeDocumentStatus(docReconciled);
check('Bonus: a recon.match exists -> Reconciled', statusReconciled.label === 'Reconciled');

// --- Challenge Agent Finding 1: fail then succeed -> Extracted (matching-eligible),
// NOT stuck on "Retrying" forever. This is Task 3.3's own stated happy path. ("Extracted",
// not "Processing", as of 2026-08-31's badge split — same matching-eligible meaning.)
const docFailThenSucceed = newDoc();
insertAttempt(docFailThenSucceed, 1, { arithmeticPass: 0, structuralPass: 1 });
insertAttempt(docFailThenSucceed, 2, { arithmeticPass: 1, structuralPass: 1 });
const statusFailThenSucceed = computeDocumentStatus(docFailThenSucceed);
check(
  'Finding 1 fix: attempt 1 fails, attempt 2 succeeds -> Extracted (not stuck on Retrying)',
  statusFailThenSucceed.label === 'Extracted'
);

// --- Challenge Agent Finding 2: Reconciled branch reports the real attempt count ---
const docReconciledWithHistory = newDoc();
insertAttempt(docReconciledWithHistory, 1, { arithmeticPass: 0, structuralPass: 1 });
insertAttempt(docReconciledWithHistory, 2, { arithmeticPass: 1, structuralPass: 1 });
reconcile(docReconciledWithHistory);
const statusReconciledWithHistory = computeDocumentStatus(docReconciledWithHistory);
check(
  'Finding 2 fix: Reconciled branch reports real attemptCount, not hardcoded 0',
  statusReconciledWithHistory.badge === 'Reconciled' && statusReconciledWithHistory.attemptCount === 2
);

// --- Challenge Agent Finding: unknown document_id fails loudly, not silently "Processing" ---
try {
  computeDocumentStatus(crypto.randomUUID());
  check('Unknown document_id throws rather than silently returning Processing', false);
} catch (e) {
  check(
    'Unknown document_id throws rather than silently returning Processing',
    /no document found/i.test(e.message)
  );
}

// --- Untested Scenario 4: 3+ attempt rows (an S7-violating state this function
// doesn't write, but should degrade sanely if it's ever fed one) ---
const docThreeAttempts = newDoc();
insertAttempt(docThreeAttempts, 1, { arithmeticPass: 0, structuralPass: 1 });
insertAttempt(docThreeAttempts, 2, { arithmeticPass: 0, structuralPass: 1 });
insertAttempt(docThreeAttempts, 3, { arithmeticPass: 0, structuralPass: 1 });
const statusThreeAttempts = computeDocumentStatus(docThreeAttempts);
check(
  'S7-violating 3-failed-attempt input still resolves to Failed, not a malformed label',
  statusThreeAttempts.label === 'Failed — see Exceptions'
);

// --- Session 6 challenge-review fix: a document with SOME lines matched and at least
// one line left as an open exception must NOT read as fully "Reconciled" — the previous
// "any match exists" check silently under-reported unresolved work. ---
{
  const documentId = newDoc();
  insertAttempt(documentId, 1, { arithmeticPass: 1, structuralPass: 1 });
  const matchedLineId = reconcile(documentId); // 1 matched line

  const vendorId = makeVendor();
  const openLineId = crypto.randomUUID();
  db.prepare(
    `INSERT INTO silver_statement_line (line_id, document_id, vendor_id, amount) VALUES (?, ?, ?, 50.00)`
  ).run(openLineId, documentId, vendorId);
  db.prepare(
    `INSERT INTO recon_exception (exception_id, statement_line_id, category, reason_codes, evidence) VALUES (?, ?, 'not_posted', '[]', '{}')`
  ).run(crypto.randomUUID(), openLineId);

  const status = computeDocumentStatus(documentId);
  check(
    'Partial match (1 matched, 1 open exception) does NOT read as Reconciled',
    status.badge !== 'Reconciled'
  );
  check(
    'Partial match surfaces as "Failed — see Exceptions" (the closed 4-value badge set\'s closest fit)',
    status.label === 'Failed — see Exceptions'
  );
  void matchedLineId;
}

// --- Session 6 challenge-review fix: a document fully matched on every line reads as
// Reconciled (the corrected, "all lines" version of the original Bonus case above). ---
{
  const documentId = newDoc();
  insertAttempt(documentId, 1, { arithmeticPass: 1, structuralPass: 1 });
  reconcile(documentId);
  const status = computeDocumentStatus(documentId);
  check('A document with every line matched reads as Reconciled', status.badge === 'Reconciled');
}

// --- Session 6 challenge-review fix: a document with zero exceptions/matches but that
// had a matching-unrelated failed extraction attempt still resolves via the existing
// Retrying/Failed extraction logic, not accidentally treated as "has an exception". ---
{
  const documentId = newDoc();
  insertAttempt(documentId, 1, { arithmeticPass: 0, structuralPass: 1 });
  const status = computeDocumentStatus(documentId);
  check('An extraction-retry document with no matching activity yet is unaffected by the new exception check', status.label === 'Retrying (1/2)');
}

await closeDb();

if (failures > 0) {
  console.error(`\n${failures} test case(s) FAILED.`);
  process.exit(1);
}
console.log('\nAll Task 2.3 test cases PASS.');
