// Task 3.3 test cases — bounded retry logic (S7: at most 2 total attempts).
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { getSqliteDb, closeDb } from '../src/lib/db.ts';
import { runMigrations } from '../src/lib/migrate.ts';
import { registerDocument } from '../src/lib/documents.ts';
import { ensureVendorStmtTable } from '../src/lib/vendorSchema.ts';
import { runExtractionPipeline } from '../src/lib/extractionPipeline.ts';
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

// --- TC-1: attempt 1 already failed (seeded directly, simulating a prior
// failed run), attempt 2 (this pipeline run) succeeds -> document proceeds to
// matching-eligible with exactly 2 attempt rows total, no 3rd attempt. ---
{
  const text = makeStatementText({
    vendor: 'Retry_Success_Vendor',
    period: '2026-07',
    total: '75.00',
    lines: [{ invoiceRef: 'INV-70', roNumber: null, amount: '75.00', date: '2026-07-15' }],
  });
  const documentId = registerTestDoc(text);

  // Seed a failed attempt_no=1 directly, as if a prior extraction run failed.
  db.prepare(
    `INSERT INTO extracted_extraction_attempt
       (attempt_id, document_id, attempt_no, raw_output, confidence, provider_used, arithmetic_pass, structural_pass)
     VALUES (?, ?, 1, 'seeded failure', NULL, 'claude_sonnet', 0, 0)`
  ).run(crypto.randomUUID(), documentId);

  await runExtractionPipeline(documentId);

  const attempts = db.prepare('SELECT attempt_no FROM extracted_extraction_attempt WHERE document_id = ? ORDER BY attempt_no').all(documentId);
  check('TC-1: exactly 2 attempt rows total (seeded 1 + this run\'s 1)', attempts.length === 2);
  check('TC-1: second attempt is attempt_no=2', attempts[1].attempt_no === 2);

  const status = computeDocumentStatus(documentId);
  // DRIFT-001 fix (2026-09-06, SPRINT-001 close-out): 'Extracted' is the correct terminal
  // badge for a successful extraction awaiting Reconcile (added 2026-08-31, distinct from
  // 'Processing', per documentStatus.ts's own comment) — this assertion predated that
  // badge and was never updated, producing a stale false FAIL (see
  // verification/VERIFICATION_CHECKLIST.md's S7 correction note).
  check('TC-1: document proceeds to matching-eligible (Extracted badge, not Failed/Retrying)', status.badge === 'Extracted');

  const silverRows = db.prepare('SELECT COUNT(*) AS n FROM silver_statement_line WHERE document_id = ?').get(documentId);
  check('TC-1: a silver.statement_line row was produced on the successful 2nd attempt', silverRows.n > 0);
}

// --- TC-2: attempt 1 fails, attempt 2 also fails -> flagged OCR_LOW_CONFIDENCE
// (surfaced via Task 2.3 as "Failed — see Exceptions"), and no 3rd attempt is
// ever triggered even if the pipeline is invoked again. ---
{
  const text = makeStatementText({
    vendor: 'Retry_Fail_Vendor',
    total: '999.00', // deliberately wrong vs. the single 10.00 line — deterministic mismatch on every attempt
    lines: [{ invoiceRef: 'INV-80', roNumber: null, amount: '10.00', date: '2026-07-16' }],
  });
  const documentId = registerTestDoc(text);

  await runExtractionPipeline(documentId);
  let attempts = db.prepare('SELECT attempt_no, arithmetic_pass FROM extracted_extraction_attempt WHERE document_id = ? ORDER BY attempt_no').all(documentId);
  check('TC-2: exactly 2 attempts made (S7 bound)', attempts.length === 2);
  check('TC-2: both attempts failed arithmetic validation', attempts.every((a) => a.arithmetic_pass === 0));

  const status = computeDocumentStatus(documentId);
  check('TC-2 (S7): document flagged OCR_LOW_CONFIDENCE, surfaced as "Failed — see Exceptions"', status.label === 'Failed — see Exceptions');

  // Re-invoking the pipeline (e.g. a stray re-trigger) must never add a 3rd attempt.
  await runExtractionPipeline(documentId);
  attempts = db.prepare('SELECT attempt_no FROM extracted_extraction_attempt WHERE document_id = ?').all(documentId);
  check('TC-2 (S7): re-invoking the pipeline never adds a 3rd attempt', attempts.length === 2);
}

// --- TC-3 (challenge-review addition): S7's bound and S10's write-guarantee
// must hold even when every attempt throws (subprocess/file I/O failure),
// not just when attempts merely fail validation. Both attempts here throw
// (document file deleted after registration), confirming the loop still
// stops at exactly 2 attempts and each attempt row lands with
// arithmetic_pass=0/structural_pass=0 rather than being silently omitted. ---
{
  const text = makeStatementText({
    vendor: 'IO_Failure_Vendor',
    total: '10.00',
    lines: [{ invoiceRef: 'INV-90', roNumber: null, amount: '10.00', date: '2026-07-17' }],
  });
  const bytes = makeTestPdf(text);
  const { document } = registerDocument(bytes, 'entity-1');
  const documentId = document.documentId;

  const uploadsDir = path.resolve(process.cwd(), process.env.UPLOADS_DIR ?? './.data/uploads');
  const filePath = path.join(uploadsDir, `${document.contentSha256}.pdf`);
  fs.rmSync(filePath, { force: true });

  await runExtractionPipeline(documentId);

  const attempts = db.prepare('SELECT arithmetic_pass, structural_pass, provider_used FROM extracted_extraction_attempt WHERE document_id = ? ORDER BY attempt_no').all(documentId);
  check('TC-3 (S7/S10): exactly 2 attempt rows written despite both attempts throwing', attempts.length === 2);
  check('TC-3 (S10): both attempts recorded as failed, not silently omitted', attempts.every((a) => a.arithmetic_pass === 0 && a.structural_pass === 0));
  check('TC-3: provider_used left null for a pre-extraction I/O failure', attempts.every((a) => a.provider_used === null));

  const status = computeDocumentStatus(documentId);
  check('TC-3 (S7): document flagged Failed after 2 thrown attempts, not stuck/unbounded', status.label === 'Failed — see Exceptions');
}

// --- TC-4 (challenge-review addition): S7's bound also holds on the
// deterministic pdfplumber route, not just the Claude-mock route — and S10's
// per-attempt raw-row write into the vendor's stmt_<vendor_slug> table
// happens once per attempt across a retry sequence, not just on success. ---
{
  const vendorId = crypto.randomUUID();
  const vendorSlug = 'retry_deterministic_vendor';
  const tableName = await ensureVendorStmtTable(vendorSlug);
  db.prepare(
    `INSERT INTO extracted_vendor_registry (vendor_id, vendor_slug, table_name, extraction_route) VALUES (?, ?, ?, 'deterministic')`
  ).run(vendorId, vendorSlug, tableName);

  const text = makeStatementText({
    vendor: 'Retry Deterministic Vendor',
    total: '999.00', // deliberately wrong vs. the single 5.00 line — deterministic mismatch on every attempt
    lines: [{ invoiceRef: 'INV-95', roNumber: null, amount: '5.00', date: '2026-07-18' }],
  });
  const documentId = registerTestDoc(text);

  await runExtractionPipeline(documentId);

  const attempts = db.prepare('SELECT provider_used, arithmetic_pass FROM extracted_extraction_attempt WHERE document_id = ?').all(documentId);
  check('TC-4 (S7): exactly 2 attempts on the deterministic route too', attempts.length === 2);
  check('TC-4: both attempts routed via python_library_pdfplumber', attempts.every((a) => a.provider_used === 'python_library_pdfplumber'));

  const rawRows = db.prepare(`SELECT COUNT(*) AS n FROM ${tableName} WHERE document_id = ?`).get(documentId);
  check('TC-4 (S10): one raw stmt row written per attempt (2 total), not just on success', rawRows.n === 2);
}

await closeDb();

if (failures > 0) {
  console.error(`\n${failures} test case(s) FAILED.`);
  process.exit(1);
}
console.log('\nAll Task 3.3 test cases PASS.');
