// Task 2.2 test cases — document registration + content-hash dedup.
// The underlying registerDocument()/documents.ts code was built as part of
// Task 2.1 (see sessions/S02_SESSION_LOG.md Decision Log — Task 2.1's own UI
// test cases required a working endpoint to exist); this script is Task 2.2's
// own dedicated verification pass against that same code, per its specific
// test cases and invariant scope (S1, G4). Exercises the actual
// POST/GET /api/documents route handlers directly (constructed Request
// objects, no running server needed — Next.js Route Handlers are plain
// functions over the standard Request/Response Web APIs), not just the
// library function beneath them.
import crypto from 'node:crypto';
import fs from 'node:fs';
import { getSqliteDb, closeDb } from '../src/lib/db.ts';
import { runMigrations } from '../src/lib/migrate.ts';
import { registerDocument, findDocumentByHash } from '../src/lib/documents.ts';
import { GET, POST } from '../src/app/api/documents/route.ts';

let failures = 0;
function check(label, condition) {
  if (condition) {
    console.log(`PASS: ${label}`);
  } else {
    console.error(`FAIL: ${label}`);
    failures++;
  }
}

function pdfRequest(bytes, legalEntityId, filename = 'test.pdf') {
  const form = new FormData();
  form.set('file', new File([bytes], filename, { type: 'application/pdf' }));
  form.set('legalEntityId', legalEntityId);
  return new Request('http://localhost/api/documents', { method: 'POST', body: form });
}

runMigrations();
const db = getSqliteDb();

// --- TC-1: uploading a genuinely new document registers cleanly, via the route ---
const bytesA = Buffer.from(`doc-a-${crypto.randomUUID()}`);
const resA = await POST(pdfRequest(bytesA, 'vive-holdings'));
const bodyA = await resA.json();
check('TC-1: POST /api/documents returns 201 for a new document', resA.status === 201);
check('TC-1: response is not marked duplicate', bodyA.duplicate === false);
check('TC-1: vendor_id is NULL at registration', bodyA.document.vendor_id === null);
check('TC-1: statement_period is NULL at registration', bodyA.document.statement_period === null);

const rawRow = db
  .prepare('SELECT previous_statement_id, is_latest_version FROM extracted_document WHERE document_id = ?')
  .get(bodyA.document.document_id);
check('TC-1: no prior version link (previous_statement_id NULL)', rawRow.previous_statement_id === null);
check('TC-1: is_latest_version defaults true', rawRow.is_latest_version === 1);

// --- GET /api/documents reflects the newly-registered document ---
const listRes = await GET();
const listBody = await listRes.json();
check(
  'GET /api/documents includes the newly-registered document',
  listBody.documents.some((d) => d.document_id === bodyA.document.document_id)
);

// --- TC-2 (G4): re-uploading the identical file (same hash) via the route, same entity ---
const countBefore = db.prepare('SELECT COUNT(*) AS n FROM extracted_document').get().n;
const resA2 = await POST(pdfRequest(bytesA, 'vive-holdings'));
const bodyA2 = await resA2.json();
const countAfter = db.prepare('SELECT COUNT(*) AS n FROM extracted_document').get().n;
check('TC-2 (G4): re-upload of identical bytes returns 200, not 201', resA2.status === 200);
check('TC-2 (G4): response is flagged duplicate', bodyA2.duplicate === true);
check(
  'TC-2 (G4): same document_id returned, no new row',
  bodyA2.document.document_id === bodyA.document.document_id && countAfter === countBefore
);
check('TC-2 (G4): no legal-entity mismatch when re-uploading under the same entity', !bodyA2.legalEntityMismatch);

// --- TC-2b (G4): re-upload of identical bytes under a DIFFERENT legal entity —
// the specific branch a prior challenge-agent pass found and fixed as a real
// bug; must not silently apply the new entity or silently succeed as if
// nothing were wrong.
const resA3 = await POST(pdfRequest(bytesA, 'vive-mid-atlantic'));
const bodyA3 = await resA3.json();
check('TC-2b (G4): duplicate under a different entity is still flagged duplicate, no new row', bodyA3.duplicate === true);
check('TC-2b (G4): legalEntityMismatch is surfaced, not silently dropped', bodyA3.legalEntityMismatch === true);
check(
  'TC-2b (G4): the originally-registered entity is preserved, not overwritten',
  bodyA3.document.legal_entity_id === 'vive-holdings'
);

// --- TC-3 (S1): registration never calls a matching service ---
// No matching-service module exists anywhere in this repo yet (Session 5 not
// built) — verified by static inspection: grep the codebase for any import
// of a matching module from documents.ts or the /api/documents route.
const documentsSrc = fs.readFileSync(new URL('../src/lib/documents.ts', import.meta.url), 'utf8');
const routeSrc = fs.readFileSync(new URL('../src/app/api/documents/route.ts', import.meta.url), 'utf8');
const mentionsMatching = /match(ing)?[-_]?service|runMatching|triggerMatch|queueMatch|invokeMatch|startReconcil/i;
check(
  'TC-3 (S1): documents.ts does not reference any matching service',
  !mentionsMatching.test(documentsSrc)
);
check(
  'TC-3 (S1): /api/documents route does not reference any matching service',
  !mentionsMatching.test(routeSrc)
);

// --- TC-4: registration does not perform vendor/period version-chaining ---
// (that logic is Task 3.1's job, once vendor is known post-extraction).
check(
  'TC-4: previous_statement_id/is_latest_version are not referenced anywhere in documents.ts',
  !/previous_statement_id|is_latest_version/i.test(documentsSrc)
);

const bytesB = Buffer.from(`doc-b-${crypto.randomUUID()}`);
const resB = await POST(pdfRequest(bytesB, 'vive-holdings'));
const bodyB = await resB.json();
const rowB = db
  .prepare('SELECT previous_statement_id, is_latest_version FROM extracted_document WHERE document_id = ?')
  .get(bodyB.document.document_id);
check(
  'TC-4: a second, unrelated document is independent — no chaining applied',
  rowB.previous_statement_id === null && rowB.is_latest_version === 1 && bodyB.document.document_id !== bodyA.document.document_id
);

// --- TC-5: check-then-insert race is handled gracefully, not an unhandled crash ---
// True concurrent-process races can't be reproduced in this single-threaded,
// synchronous test — this instead confirms the detection logic registerDocument's
// catch block relies on: a raw duplicate INSERT against content_sha256's UNIQUE
// constraint actually produces the error message shape being matched against.
try {
  db.prepare(
    `INSERT INTO extracted_document (document_id, content_sha256, legal_entity_id) VALUES (?, ?, ?)`
  ).run(crypto.randomUUID(), bodyA.document.content_sha256, 'vive-holdings');
  check('TC-5: raw duplicate INSERT throws (UNIQUE constraint)', false);
} catch (e) {
  check('TC-5: UNIQUE-constraint error message matches registerDocument\'s race-recovery detection', /UNIQUE constraint failed/i.test(e.message));
}
// registerDocument itself still works correctly for a genuinely new document
// after that raw-SQL probe (confirms the probe didn't corrupt DB state).
const bytesC = Buffer.from(`doc-c-${crypto.randomUUID()}`);
const { duplicate: dupC } = registerDocument(bytesC, 'vive-holdings');
check('TC-5: registerDocument still works normally after the race-detection probe', dupC === false);

await closeDb();

if (failures > 0) {
  console.error(`\n${failures} test case(s) FAILED.`);
  process.exit(1);
}
console.log('\nAll Task 2.2 test cases PASS.');
