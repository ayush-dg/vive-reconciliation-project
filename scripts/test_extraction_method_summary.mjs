// Task 3.5 test cases — extraction-method summary (per-document counts by provider_used).
import crypto from 'node:crypto';
import { getSqliteDb, closeDb } from '../src/lib/db.ts';
import { runMigrations } from '../src/lib/migrate.ts';
import { registerDocument } from '../src/lib/documents.ts';
import { runExtractionPipeline } from '../src/lib/extractionPipeline.ts';
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

function registerTestDoc(text, legalEntityId = 'entity-1') {
  const bytes = makeTestPdf(text);
  const { document } = registerDocument(bytes, legalEntityId);
  return document.documentId;
}

function seedAttempt(documentId, attemptNo, providerUsed) {
  db.prepare(
    `INSERT INTO extracted_extraction_attempt
       (attempt_id, document_id, attempt_no, raw_output, confidence, provider_used, arithmetic_pass, structural_pass)
     VALUES (?, ?, ?, 'seeded', NULL, ?, 1, 1)`
  ).run(crypto.randomUUID(), documentId, attemptNo, providerUsed);
}

// --- TC-1: a document extracted entirely via claude_sonnet -> summary with only that key. ---
{
  const text = makeStatementText({
    vendor: 'Summary_Claude_Vendor',
    total: '20.00',
    lines: [{ invoiceRef: 'INV-1', roNumber: null, amount: '20.00', date: '2026-07-01' }],
  });
  const documentId = registerTestDoc(text);
  await runExtractionPipeline(documentId); // routes to claude_sonnet (unregistered vendor)

  const summary = getExtractionMethodSummary(documentId);
  check('TC-1: summary has exactly one key', Object.keys(summary).length === 1);
  check('TC-1: only claude_sonnet is populated', summary.claude_sonnet === 1);
  check('TC-1: python_library_pdfplumber is absent, not zero', summary.python_library_pdfplumber === undefined);
}

// --- TC-2: a document with some pdfplumber-fallback rows shows both providers with correct
// counts. No task in this session implements routing TO pdfplumber_fallback (see this
// task's Scope Decision note — flagged as an out-of-scope observation, not fixed here);
// this test seeds the value directly to prove the summary's aggregation logic is agnostic
// to which provider values actually occur, exactly as documentStatus.ts's own tests already
// do for attempt data (seeded rows, not a live pipeline requirement). ---
{
  const documentId = registerTestDoc(
    makeStatementText({ vendor: 'Summary_Mixed_Vendor', total: '5.00', lines: [{ invoiceRef: 'INV-2', roNumber: null, amount: '5.00', date: '2026-07-02' }] })
  );
  seedAttempt(documentId, 1, 'claude_sonnet');
  seedAttempt(documentId, 2, 'pdfplumber_fallback');
  seedAttempt(documentId, 3, 'pdfplumber_fallback');

  const summary = getExtractionMethodSummary(documentId);
  check('TC-2: both providers present', Object.keys(summary).sort().join(',') === 'claude_sonnet,pdfplumber_fallback');
  check('TC-2: claude_sonnet count correct', summary.claude_sonnet === 1);
  check('TC-2: pdfplumber_fallback count correct', summary.pdfplumber_fallback === 2);
}

// --- TC-3: a document with no attempts yet -> empty summary, not an error. ---
{
  const documentId = registerTestDoc(
    makeStatementText({ vendor: 'No_Attempts_Vendor', total: '1.00', lines: [{ invoiceRef: 'INV-3', roNumber: null, amount: '1.00', date: '2026-07-03' }] })
  );
  const summary = getExtractionMethodSummary(documentId);
  check('TC-3: no attempts -> empty summary object', Object.keys(summary).length === 0);
}

// --- TC-4: the deterministic route's own provider value is counted correctly too. ---
{
  const vendorId = crypto.randomUUID();
  const { ensureVendorStmtTable } = await import('../src/lib/vendorSchema.ts');
  const tableName = await ensureVendorStmtTable('summary_deterministic_vendor');
  db.prepare(
    `INSERT INTO extracted_vendor_registry (vendor_id, vendor_slug, table_name, extraction_route) VALUES (?, ?, ?, 'deterministic')`
  ).run(vendorId, 'summary_deterministic_vendor', tableName);

  const documentId = registerTestDoc(
    makeStatementText({ vendor: 'Summary Deterministic Vendor', total: '8.00', lines: [{ invoiceRef: 'INV-4', roNumber: null, amount: '8.00', date: '2026-07-04' }] })
  );
  await runExtractionPipeline(documentId);

  const summary = getExtractionMethodSummary(documentId);
  check('TC-4: deterministic-route document counts under python_library_pdfplumber', summary.python_library_pdfplumber === 1);
}

// --- TC-5 (challenge-review addition): a nonexistent document_id must fail loudly, not
// return a plausible-looking-but-wrong empty summary indistinguishable from a real
// zero-attempt document (TC-3) — matches documentStatus.ts's own established pattern for
// this exact ambiguity. ---
{
  let threw = false;
  try {
    getExtractionMethodSummary('00000000-0000-0000-0000-000000000000');
  } catch {
    threw = true;
  }
  check('TC-5: unknown document_id throws rather than silently returning {}', threw);
}

// --- TC-6 (challenge-review addition): an attempt with provider_used=NULL (a catastrophic
// pre-provider-selection failure — extractionPipeline.ts's catch block) must surface under
// an explicit "unknown" bucket, not be silently dropped and collapse into the same {}
// output as a genuine zero-attempt document. ---
{
  const documentId = registerTestDoc(
    makeStatementText({ vendor: 'Null_Provider_Vendor', total: '9.00', lines: [{ invoiceRef: 'INV-9', roNumber: null, amount: '9.00', date: '2026-07-09' }] })
  );
  seedAttempt(documentId, 1, null);
  const summary = getExtractionMethodSummary(documentId);
  check('TC-6: a NULL provider_used attempt surfaces under "unknown", not silently dropped', summary.unknown === 1);
}

// --- TC-7 (challenge-review addition): two distinct documents with the same provider must
// stay isolated by document_id — an explicit, designed assertion rather than an incidental
// side effect of test ordering. ---
{
  const docA = registerTestDoc(
    makeStatementText({ vendor: 'Isolation_Vendor_A', total: '1.00', lines: [{ invoiceRef: 'INV-A', roNumber: null, amount: '1.00', date: '2026-07-10' }] })
  );
  const docB = registerTestDoc(
    makeStatementText({ vendor: 'Isolation_Vendor_B', total: '1.00', lines: [{ invoiceRef: 'INV-B', roNumber: null, amount: '1.00', date: '2026-07-11' }] })
  );
  seedAttempt(docA, 1, 'claude_sonnet');
  seedAttempt(docB, 1, 'claude_sonnet');
  seedAttempt(docB, 2, 'claude_sonnet');

  check('TC-7: document A sees only its own attempt', getExtractionMethodSummary(docA).claude_sonnet === 1);
  check('TC-7: document B sees only its own attempts, not A\'s', getExtractionMethodSummary(docB).claude_sonnet === 2);
}

await closeDb();

if (failures > 0) {
  console.error(`\n${failures} test case(s) FAILED.`);
  process.exit(1);
}
console.log('\nAll Task 3.5 test cases PASS.');
