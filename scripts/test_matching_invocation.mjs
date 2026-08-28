// Task 5.1 test cases — matching invocation (manual + scheduled), S1 + G5.
import fs from 'node:fs';
import crypto from 'node:crypto';
import { getSqliteDb, closeDb } from '../src/lib/db.ts';
import { runMigrations } from '../src/lib/migrate.ts';
import { registerDocument } from '../src/lib/documents.ts';
import {
  triggerMatchingForDocument,
  runScheduledMatchingBatch,
  acquireMatchingLock,
  releaseMatchingLock,
} from '../src/lib/matchingInvocation.ts';
import { makeTestPdf } from './testPdfFixture.mjs';

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

function registerTestDoc(legalEntityId = 'entity-1') {
  const bytes = makeTestPdf(`irrelevant-${crypto.randomUUID()}`);
  const { document } = registerDocument(bytes, legalEntityId);
  return document.documentId;
}

function insertSilverLine(documentId, invoiceRef = 'INV-1') {
  const vendorId = crypto.randomUUID();
  db.prepare(
    `INSERT INTO extracted_vendor_registry (vendor_id, vendor_slug, table_name, extraction_route) VALUES (?, ?, ?, NULL)`
  ).run(vendorId, `test_vendor_${vendorId.slice(0, 8)}`, `extracted_stmt_test_${vendorId.slice(0, 8)}`);
  db.prepare(
    `INSERT INTO silver_statement_line (line_id, document_id, vendor_id, amount, invoice_ref, normalized_invoice_ref, normalization_version)
     VALUES (?, ?, ?, ?, ?, ?, 'v1')`
  ).run(crypto.randomUUID(), documentId, vendorId, 10, invoiceRef, invoiceRef.toUpperCase());
}

// --- TC-1: manual API trigger executes matching against currently eligible StatementLines. ---
{
  const documentId = registerTestDoc();
  insertSilverLine(documentId);
  const result = await triggerMatchingForDocument(documentId);
  check('TC-1: manual trigger succeeds for an existing document', result.ok === true);
}

// --- TC-2: scheduled batch job executes matching on its configured cadence (i.e. the
// callable batch function processes eligible documents when invoked). ---
{
  const documentId = registerTestDoc();
  insertSilverLine(documentId);
  const result = await runScheduledMatchingBatch();
  check('TC-2: scheduled batch processes the eligible document', result.processed.includes(documentId));
}

// --- TC-3 (S1): uploading a document (Task 2.2's registerDocument) does not itself
// invoke matching — structural check: documents.ts never imports matchingInvocation.ts. ---
{
  const documentsSource = fs.readFileSync('src/lib/documents.ts', 'utf8');
  check('TC-3 (S1): documents.ts does not import matchingInvocation.ts', !documentsSource.includes('matchingInvocation'));

  // Behavioral confirmation: a freshly-registered document with a silver line sits
  // eligible (no match/exception row) until matching is explicitly invoked.
  const documentId = registerTestDoc();
  insertSilverLine(documentId);
  const matchCount = db.prepare('SELECT COUNT(*) AS n FROM recon_match WHERE statement_line_id IN (SELECT line_id FROM silver_statement_line WHERE document_id = ?)').get(documentId);
  check('TC-3 (S1): registering a document creates no recon.match row on its own', matchCount.n === 0);
}

// --- TC-4 (G5): the atomic lock guard — a second acquisition attempt for the same
// document fails while the first still holds it; releasing allows a future re-acquisition
// (matching is repeatable, unlike Task 2.4's one-way extraction lock). ---
{
  const documentId = registerTestDoc();
  const first = acquireMatchingLock(documentId);
  const second = acquireMatchingLock(documentId);
  check('TC-4 (G5): first lock acquisition succeeds', first === true);
  check('TC-4 (G5): second concurrent acquisition attempt fails — never double-processed', second === false);
  releaseMatchingLock(documentId);
  const third = acquireMatchingLock(documentId);
  check('TC-4 (G5): after release, the same document can be locked again (matching is repeatable)', third === true);
  releaseMatchingLock(documentId);
}

// --- TC-5 (G5, end-to-end): a manual trigger and a concurrent scheduled batch run over
// the same eligible document — the document is matched exactly once, never twice; the
// batch run correctly reports it as skipped since the manual path already holds the lock. ---
{
  const documentId = registerTestDoc();
  insertSilverLine(documentId);

  const lockedByManual = acquireMatchingLock(documentId); // simulates the manual trigger already in flight
  check('TC-5: manual path acquires the lock first', lockedByManual === true);

  const batchResult = await runScheduledMatchingBatch();
  check('TC-5 (G5): the scheduled batch skips the document already locked by the manual path', batchResult.skipped.includes(documentId));
  check('TC-5 (G5): the scheduled batch does not also process it', !batchResult.processed.includes(documentId));

  releaseMatchingLock(documentId);
}

// --- TC-7 (challenge-review addition, G5): a lock abandoned by a hard crash (never
// released) must eventually be reclaimable — otherwise a document could become
// permanently unmatchable. Simulates an abandoned lock by backdating acquired_at past the
// staleness threshold directly, then confirms a fresh acquisition succeeds. ---
{
  const documentId = registerTestDoc();
  const acquired = acquireMatchingLock(documentId);
  check('TC-7: initial lock acquisition succeeds', acquired === true);

  db.prepare(`UPDATE recon_document_lock SET acquired_at = datetime('now', '-15 minutes') WHERE document_id = ?`).run(documentId);
  const reacquired = acquireMatchingLock(documentId);
  check('TC-7 (G5): a stale (abandoned) lock is reclaimable, not permanent', reacquired === true);

  releaseMatchingLock(documentId);
}

// --- TC-8 (challenge-review addition, G5): a FRESH lock (well within the staleness
// window) must NOT be reclaimable by a second acquisition attempt — confirms the
// staleness fix didn't weaken the core mutual-exclusion guarantee TC-4 already covers. ---
{
  const documentId = registerTestDoc();
  const first = acquireMatchingLock(documentId);
  const second = acquireMatchingLock(documentId);
  check('TC-8: first acquisition succeeds', first === true);
  check('TC-8 (G5): a fresh, still-held lock is NOT reclaimable', second === false);
  releaseMatchingLock(documentId);
}

// --- TC-9 (challenge-review addition, G5): recon.document_lock.document_id has a FK
// reference to extracted.document, matching every other document-linking column in this
// schema — acquiring a lock for a nonexistent document_id must fail, not silently succeed. ---
{
  let threw = false;
  try {
    acquireMatchingLock('00000000-0000-0000-0000-000000000000');
  } catch {
    threw = true;
  }
  check('TC-9 (G5): acquiring a lock for a nonexistent document_id fails (FK enforced)', threw);
}

// --- TC-6: triggering matching for a nonexistent document returns not_found, not a throw. ---
{
  const result = await triggerMatchingForDocument('00000000-0000-0000-0000-000000000000');
  check('TC-6: unknown document_id returns not_found', result.ok === false && result.reason === 'not_found');
}

await closeDb();

if (failures > 0) {
  console.error(`\n${failures} test case(s) FAILED.`);
  process.exit(1);
}
console.log('\nAll Task 5.1 test cases PASS.');
