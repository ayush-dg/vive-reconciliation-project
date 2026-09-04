// ENH-001 Task 2.1 test cases — extraction crash-recovery fix (IC-CANDIDATE-01 / R-005),
// Silver-normalization path.
import crypto from 'node:crypto';
import { getSqliteDb, closeDb } from '../src/lib/db.ts';
import { runMigrations } from '../src/lib/migrate.ts';
import { registerDocument } from '../src/lib/documents.ts';
import { runExtractionPipeline, SilverNormalizationFailure, RecoveryAttemptsExhausted } from '../src/lib/extractionPipeline.ts';
import { triggerExtraction } from '../src/lib/extraction.ts';
import { computeDocumentStatus } from '../src/lib/documentStatus.ts';
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

// Forces a genuine normalizeToSilver() failure by making its INSERT target
// disappear mid-pipeline — same "direct DB state manipulation" technique this
// codebase's other tests use (e.g. test_bounded_retry.mjs seeding attempt rows
// directly), applied here since there's no code hook to inject a Silver-layer
// failure without this trick or a mocking framework this codebase doesn't use.
function disableSilverTable() {
  db.exec('ALTER TABLE silver_statement_line RENAME TO silver_statement_line_disabled_for_test');
}
function restoreSilverTable() {
  db.exec('ALTER TABLE silver_statement_line_disabled_for_test RENAME TO silver_statement_line');
}

// --- TC-1: extraction succeeds and validates, but Silver normalization
// throws -> the attempt row is still correctly written (pass=1/1, per S10/G1
// — this task must not change that), and the thrown error is specifically
// SilverNormalizationFailure, not a generic Error. ---
{
  const text = makeStatementText({
    vendor: 'Crash_Recovery_Vendor_1',
    total: '50.00',
    lines: [{ invoiceRef: 'INV-CR1', roNumber: null, amount: '50.00', date: '2026-07-20' }],
  });
  const documentId = registerTestDoc(text);

  disableSilverTable();
  let caught = null;
  try {
    await runExtractionPipeline(documentId);
  } catch (err) {
    caught = err;
  } finally {
    restoreSilverTable();
  }

  check('TC-1: runExtractionPipeline throws when Silver normalization fails', caught !== null);
  check('TC-1: the thrown error is specifically SilverNormalizationFailure', caught instanceof SilverNormalizationFailure);

  const attempts = db.prepare('SELECT attempt_no, arithmetic_pass, structural_pass FROM extracted_extraction_attempt WHERE document_id = ?').all(documentId);
  check('TC-1: exactly 1 attempt row written despite the Silver failure', attempts.length === 1);
  check('TC-1: the attempt row correctly shows pass=1/1 (extraction genuinely succeeded)', attempts[0].arithmetic_pass === 1 && attempts[0].structural_pass === 1);

  const silverRows = db.prepare('SELECT COUNT(*) AS n FROM silver_statement_line WHERE document_id = ?').get(documentId);
  check('TC-1: zero Silver rows exist (the write never completed)', silverRows.n === 0);
}

// --- TC-2: a skipSuccessGuard recovery retry, with an attempt slot still
// available (this was attempt 1 of 2), re-runs extraction and succeeds —
// exactly 2 total attempts, Silver rows now present. ---
{
  const text = makeStatementText({
    vendor: 'Crash_Recovery_Vendor_2',
    total: '60.00',
    lines: [{ invoiceRef: 'INV-CR2', roNumber: null, amount: '60.00', date: '2026-07-21' }],
  });
  const documentId = registerTestDoc(text);

  disableSilverTable();
  try {
    await runExtractionPipeline(documentId);
  } catch {
    // expected — see TC-1
  } finally {
    restoreSilverTable();
  }

  await runExtractionPipeline(documentId, { skipSuccessGuard: true });

  const attempts = db.prepare('SELECT attempt_no FROM extracted_extraction_attempt WHERE document_id = ? ORDER BY attempt_no').all(documentId);
  check('TC-2: exactly 2 total attempts (1 failed-Silver + 1 recovery)', attempts.length === 2);
  check('TC-2: recovery attempt is attempt_no=2', attempts[1].attempt_no === 2);

  const silverRows = db.prepare('SELECT COUNT(*) AS n FROM silver_statement_line WHERE document_id = ?').get(documentId);
  check('TC-2: Silver rows now exist after the successful recovery retry', silverRows.n > 0);

  const status = computeDocumentStatus(documentId);
  check('TC-2: document is matching-eligible (Extracted badge) after recovery', status.badge === 'Extracted');
}

// --- TC-3: a skipSuccessGuard recovery retry with NO attempt slots left
// (the Silver failure happened on attempt 2, S7's last allowed one) throws
// RecoveryAttemptsExhausted rather than silently no-op'ing — the gap found
// and fixed beyond the execution plan's original Option B design. ---
{
  const text = makeStatementText({
    vendor: 'Crash_Recovery_Vendor_3',
    total: '70.00',
    lines: [{ invoiceRef: 'INV-CR3', roNumber: null, amount: '70.00', date: '2026-07-22' }],
  });
  const documentId = registerTestDoc(text);

  // Seed attempt 1 as a genuine validation failure (as if a prior run failed
  // normally), then force attempt 2 (this run) to succeed extraction/validation
  // but fail Silver — landing exactly on S7's last allowed attempt.
  db.prepare(
    `INSERT INTO extracted_extraction_attempt
       (attempt_id, document_id, attempt_no, raw_output, confidence, provider_used, arithmetic_pass, structural_pass)
     VALUES (?, ?, 1, 'seeded failure', NULL, 'claude_sonnet', 0, 0)`
  ).run(crypto.randomUUID(), documentId);

  disableSilverTable();
  try {
    await runExtractionPipeline(documentId);
  } catch {
    // expected — see TC-1
  } finally {
    restoreSilverTable();
  }

  const attemptsBefore = db.prepare('SELECT attempt_no FROM extracted_extraction_attempt WHERE document_id = ?').all(documentId);
  check('TC-3 setup: attempt 2 (the last allowed) is the one that failed Silver', attemptsBefore.length === 2);

  let caught = null;
  try {
    await runExtractionPipeline(documentId, { skipSuccessGuard: true });
  } catch (err) {
    caught = err;
  }
  check('TC-3: the exhausted recovery retry throws, not silently returns', caught !== null);
  check('TC-3: the thrown error is specifically RecoveryAttemptsExhausted', caught instanceof RecoveryAttemptsExhausted);

  const attemptsAfter = db.prepare('SELECT attempt_no FROM extracted_extraction_attempt WHERE document_id = ?').all(documentId);
  check('TC-3: no 3rd attempt row was written — S7\'s bound still holds', attemptsAfter.length === 2);
}

// --- TC-4: triggerExtraction() (M-015) end-to-end — a Silver-normalization
// failure resets document.status to 're-triggerable' (not stuck at
// 'processing'), and the NEXT trigger call automatically detects the stuck
// state (needsSilverRecovery) and retries with skipSuccessGuard: true,
// without the caller needing to know anything about the recovery mechanism. ---
{
  const text = makeStatementText({
    vendor: 'Crash_Recovery_Vendor_4',
    total: '80.00',
    lines: [{ invoiceRef: 'INV-CR4', roNumber: null, amount: '80.00', date: '2026-07-23' }],
  });
  const documentId = registerTestDoc(text);

  disableSilverTable();
  const firstResult = await triggerExtraction(documentId);
  restoreSilverTable();

  check('TC-4: triggerExtraction reports ok (recoverable, not a hard failure)', firstResult.ok === true);

  const statusAfterFailure = db.prepare('SELECT status FROM extracted_document WHERE document_id = ?').get(documentId);
  check("TC-4: document.status reset to 'registered' after the Silver failure, not stuck at 'processing'", statusAfterFailure.status === 'registered');

  const secondResult = await triggerExtraction(documentId);
  check('TC-4: the automatic recovery retrigger succeeds', secondResult.ok === true);

  const attempts = db.prepare('SELECT attempt_no FROM extracted_extraction_attempt WHERE document_id = ?').all(documentId);
  check('TC-4: exactly 2 total attempts across both trigger calls', attempts.length === 2);

  const silverRows = db.prepare('SELECT COUNT(*) AS n FROM silver_statement_line WHERE document_id = ?').get(documentId);
  check('TC-4: Silver rows exist after the automatic recovery', silverRows.n > 0);
}

// --- TC-5 (regression): G5's atomic guard is unchanged by this task — a
// second trigger while one is genuinely already in flight (status='processing')
// is still rejected outright, never silently re-queued or double-processed. ---
{
  const text = makeStatementText({
    vendor: 'Crash_Recovery_Vendor_5',
    total: '90.00',
    lines: [{ invoiceRef: 'INV-CR5', roNumber: null, amount: '90.00', date: '2026-07-24' }],
  });
  const documentId = registerTestDoc(text);

  db.prepare(`UPDATE extracted_document SET status = 'processing' WHERE document_id = ?`).run(documentId);

  const result = await triggerExtraction(documentId);
  check('TC-5 (G5 regression): a trigger while genuinely processing is rejected, not re-queued', result.ok === false && result.reason === 'already_processing');

  const attempts = db.prepare('SELECT COUNT(*) AS n FROM extracted_extraction_attempt WHERE document_id = ?').get(documentId);
  check('TC-5: no attempt was made — the guard rejected before the pipeline ever ran', attempts.n === 0);
}

// --- TC-6 (challenge agent Finding 1): triggerExtraction() itself — not just
// runExtractionPipeline() directly — correctly handles RecoveryAttemptsExhausted:
// status resets to 'registered' and the caller gets { ok: false,
// reason: 'recovery_exhausted' }, not a false "extraction started" success. ---
{
  const text = makeStatementText({
    vendor: 'Crash_Recovery_Vendor_6',
    total: '85.00',
    lines: [{ invoiceRef: 'INV-CR6', roNumber: null, amount: '85.00', date: '2026-07-25' }],
  });
  const documentId = registerTestDoc(text);

  // Seed attempt 1 as a normal failure, then force attempt 2 (this trigger) to succeed
  // extraction/validation but fail Silver — landing exactly on S7's last allowed attempt,
  // same setup as TC-3 but driven through triggerExtraction() this time.
  db.prepare(
    `INSERT INTO extracted_extraction_attempt
       (attempt_id, document_id, attempt_no, raw_output, confidence, provider_used, arithmetic_pass, structural_pass)
     VALUES (?, ?, 1, 'seeded failure', NULL, 'claude_sonnet', 0, 0)`
  ).run(crypto.randomUUID(), documentId);

  disableSilverTable();
  await triggerExtraction(documentId);
  restoreSilverTable();

  const statusAfterFirstFailure = db.prepare('SELECT status FROM extracted_document WHERE document_id = ?').get(documentId);
  check("TC-6 setup: status reset to 'registered' after the Silver failure on the last attempt", statusAfterFirstFailure.status === 'registered');

  const result = await triggerExtraction(documentId);
  check('TC-6: triggerExtraction reports the exhausted recovery as a distinct failure', result.ok === false && result.reason === 'recovery_exhausted');

  const statusAfterExhausted = db.prepare('SELECT status FROM extracted_document WHERE document_id = ?').get(documentId);
  check("TC-6: status reset to 'registered' after the exhausted recovery too, not stuck at 'processing'", statusAfterExhausted.status === 'registered');
}

// --- TC-7 (challenge agent Finding 2): the generic-error fallthrough — an error that
// is neither SilverNormalizationFailure nor RecoveryAttemptsExhausted still resets
// document.status to 'registered' AND is rethrown to the caller, exactly as the task's
// own design text specifies ("Any other thrown error gets a plain status reset with no
// special retry path"). Forced by reproducing the exact historical bug
// ensureKnownVendor's own doc comment describes (vendorIdentification.ts:104-112): a
// vendor_registry row naming a table_name that was never actually created. Registering
// the row directly (matching test_bounded_retry.mjs TC-4's pattern) routes through the
// `matched.extractionRoute === 'deterministic'` branch, which — unlike the real
// known-vendor path — has no ensureVendorStmtTable() safety net, so the raw-row INSERT
// throws a genuine, uncategorized SqliteError, not one of this task's two new types. ---
{
  const vendorId = crypto.randomUUID();
  const vendorSlug = 'crash_recovery_bogus_table_vendor';
  db.prepare(
    `INSERT INTO extracted_vendor_registry (vendor_id, vendor_slug, table_name, extraction_route)
     VALUES (?, ?, 'extracted_stmt_never_actually_created', 'deterministic')`
  ).run(vendorId, vendorSlug);

  const vendorNameForSlug = vendorSlug.replace(/_/g, ' ');
  const text = makeStatementText({
    vendor: vendorNameForSlug,
    total: '95.00',
    lines: [{ invoiceRef: 'INV-CR7', roNumber: null, amount: '95.00', date: '2026-07-26' }],
  });
  const documentId = registerTestDoc(text);

  let caught = null;
  try {
    await triggerExtraction(documentId);
  } catch (err) {
    caught = err;
  }

  check('TC-7: a generic error is rethrown to the caller, not swallowed', caught !== null);
  check(
    "TC-7: the rethrown error is neither of this task's two special-cased types",
    !(caught instanceof SilverNormalizationFailure) && !(caught instanceof RecoveryAttemptsExhausted)
  );

  const status = db.prepare('SELECT status FROM extracted_document WHERE document_id = ?').get(documentId);
  check("TC-7: status still reset to 'registered' even on a generic, uncategorized error", status.status === 'registered');

  const attempts = db.prepare('SELECT arithmetic_pass, structural_pass FROM extracted_extraction_attempt WHERE document_id = ?').all(documentId);
  check('TC-7: the attempt row was still written before the raw-row insert failed (S10 unaffected)', attempts.length === 1);
}

await closeDb();

if (failures > 0) {
  console.error(`\n${failures} test case(s) FAILED.`);
  process.exit(1);
}
console.log('\nAll Task 2.1 test cases PASS.');
