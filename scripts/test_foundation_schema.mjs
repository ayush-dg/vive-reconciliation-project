// Task 1.2 test cases, run against local SQLite (the Fabric-side Verification
// Command in EXECUTION_PLAN.md — sqlcmd against a live FABRIC_SQL_ENDPOINT — has
// no live endpoint available in this environment; see Known Untested Scenarios
// in sessions/S01_VERIFICATION_RECORD.md Task 1.2).
import crypto from 'node:crypto';
import { getSqliteDb, closeDb } from '../src/lib/db.ts';
import { runMigrations } from '../src/lib/migrate.ts';
import { ensureVendorStmtTable } from '../src/lib/vendorSchema.ts';
import { assertValidVendorSlug } from '../src/lib/schema.ts';

function uuid() {
  return crypto.randomUUID();
}

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

// --- TC-1: insert extracted_document with all required fields succeeds ---
const docId1 = uuid();
try {
  db.prepare(
    `INSERT INTO extracted_document (document_id, content_sha256, legal_entity_id)
     VALUES (?, ?, ?)`
  ).run(docId1, crypto.createHash('sha256').update('doc-1').digest('hex'), 'entity-1');
  check('TC-1: insert document with required fields succeeds', true);
} catch (e) {
  check(`TC-1: insert document with required fields succeeds (${e.message})`, false);
}

// --- TC-2: insert extracted_document with legal_entity_id = NULL is rejected (S4) ---
try {
  db.prepare(
    `INSERT INTO extracted_document (document_id, content_sha256, legal_entity_id)
     VALUES (?, ?, NULL)`
  ).run(uuid(), crypto.createHash('sha256').update('doc-2').digest('hex'));
  check('TC-2: NULL legal_entity_id is rejected (S4)', false);
} catch (e) {
  check(`TC-2: NULL legal_entity_id is rejected (S4) — ${e.message}`, /NOT NULL/i.test(e.message));
}

// --- TC-3: vendor registry resolves a known vendor_id to its stmt_<slug> table name ---
const vendorId = uuid();
const vendorSlug = 'fred_beans';
const resolvedTableName = await ensureVendorStmtTable(vendorSlug);
db.prepare(
  `INSERT INTO extracted_vendor_registry (vendor_id, vendor_slug, table_name, extraction_route)
   VALUES (?, ?, ?, 'deterministic')`
).run(vendorId, vendorSlug, resolvedTableName);
const row = db
  .prepare('SELECT table_name FROM extracted_vendor_registry WHERE vendor_id = ?')
  .get(vendorId);
check(
  `TC-3: vendor registry resolves vendor_id -> table name (${row?.table_name})`,
  row?.table_name === `extracted_stmt_${vendorSlug}`
);

// --- TC-4: insert recon_exception with unrecognized category is rejected (S5) ---
db.prepare(
  `INSERT INTO extracted_document (document_id, content_sha256, legal_entity_id, vendor_id)
   VALUES (?, ?, ?, ?)`
).run(uuid(), crypto.createHash('sha256').update('doc-3').digest('hex'), 'entity-1', vendorId);
const docForLine = db
  .prepare('SELECT document_id FROM extracted_document WHERE vendor_id = ?')
  .get(vendorId);
const lineId = uuid();
db.prepare(
  `INSERT INTO silver_statement_line (line_id, document_id, vendor_id, amount)
   VALUES (?, ?, ?, 100.00)`
).run(lineId, docForLine.document_id, vendorId);

try {
  db.prepare(
    `INSERT INTO recon_exception (exception_id, statement_line_id, category)
     VALUES (?, ?, 'not_a_real_category')`
  ).run(uuid(), lineId);
  check('TC-4: unrecognized exception category is rejected (S5)', false);
} catch (e) {
  check(`TC-4: unrecognized exception category is rejected (S5) — ${e.message}`, /CHECK/i.test(e.message));
}

// --- TC-5: UPDATE on an existing extraction_attempt row fails (G1) ---
const attemptId = uuid();
db.prepare(
  `INSERT INTO extracted_extraction_attempt (attempt_id, document_id, attempt_no)
   VALUES (?, ?, 1)`
).run(attemptId, docId1);
try {
  db.prepare(`UPDATE extracted_extraction_attempt SET attempt_no = 2 WHERE attempt_id = ?`).run(attemptId);
  check('TC-5: UPDATE on extraction_attempt row fails (G1, append-only)', false);
} catch (e) {
  check(`TC-5: UPDATE on extraction_attempt row fails (G1, append-only) — ${e.message}`, /append-only/i.test(e.message));
}

// --- TC-5b: same, for a stmt_<vendor_slug> table ---
const stmtRowId = uuid();
db.prepare(
  `INSERT INTO ${resolvedTableName} (row_id, document_id, raw_row) VALUES (?, ?, '{}')`
).run(stmtRowId, docForLine.document_id);
try {
  db.prepare(`UPDATE ${resolvedTableName} SET raw_row = '{"changed":true}' WHERE row_id = ?`).run(stmtRowId);
  check('TC-5b: UPDATE on extracted.stmt_* row fails (G1, append-only)', false);
} catch (e) {
  check(`TC-5b: UPDATE on extracted.stmt_* row fails (G1, append-only) — ${e.message}`, /append-only/i.test(e.message));
}

// --- Bonus: S11 — silver_statement_line.amount immutable ---
try {
  db.prepare(`UPDATE silver_statement_line SET amount = 999.99 WHERE line_id = ?`).run(lineId);
  check('S11: UPDATE on statement_line.amount fails (append-only amount)', false);
} catch (e) {
  check(`S11: UPDATE on statement_line.amount fails (append-only amount) — ${e.message}`, /immutable/i.test(e.message));
}

// --- Challenge Agent Finding: G1's FK-validity half — invalid document_id rejected ---
try {
  db.prepare(
    `INSERT INTO extracted_extraction_attempt (attempt_id, document_id, attempt_no) VALUES (?, ?, 1)`
  ).run(uuid(), 'nonexistent-document-id');
  check('G1: extraction_attempt with invalid document_id is rejected (FK)', false);
} catch (e) {
  check(`G1: extraction_attempt with invalid document_id is rejected (FK) — ${e.message}`, /FOREIGN KEY/i.test(e.message));
}

// --- Challenge Agent Finding: G4 — duplicate content_sha256 is rejected (UNIQUE) ---
const dupeHash = crypto.createHash('sha256').update('dupe-doc').digest('hex');
db.prepare(
  `INSERT INTO extracted_document (document_id, content_sha256, legal_entity_id) VALUES (?, ?, 'entity-1')`
).run(uuid(), dupeHash);
try {
  db.prepare(
    `INSERT INTO extracted_document (document_id, content_sha256, legal_entity_id) VALUES (?, ?, 'entity-1')`
  ).run(uuid(), dupeHash);
  check('G4: duplicate content_sha256 is rejected (UNIQUE)', false);
} catch (e) {
  check(`G4: duplicate content_sha256 is rejected (UNIQUE) — ${e.message}`, /UNIQUE/i.test(e.message));
}

// --- Challenge Agent Finding: provider_used / extraction_route CHECK constraints ---
try {
  db.prepare(
    `INSERT INTO extracted_extraction_attempt (attempt_id, document_id, attempt_no, provider_used) VALUES (?, ?, 1, 'not_a_real_provider')`
  ).run(uuid(), docId1);
  check('provider_used CHECK rejects an invalid value', false);
} catch (e) {
  check(`provider_used CHECK rejects an invalid value — ${e.message}`, /CHECK/i.test(e.message));
}
try {
  db.prepare(
    `INSERT INTO extracted_vendor_registry (vendor_id, vendor_slug, table_name, extraction_route) VALUES (?, 'bad_route_vendor', 'extracted_stmt_bad_route_vendor', 'not_a_real_route')`
  ).run(uuid());
  check('extraction_route CHECK rejects an invalid value', false);
} catch (e) {
  check(`extraction_route CHECK rejects an invalid value — ${e.message}`, /CHECK/i.test(e.message));
}

// --- Challenge Agent Finding: migration idempotency — re-running does not fail ---
try {
  const second = runMigrations();
  check(
    `Migration re-run is idempotent (applied=${second.applied.length}, skipped=${second.skipped.length})`,
    second.applied.length === 0 && second.skipped.length === 1
  );
} catch (e) {
  check(`Migration re-run is idempotent (${e.message})`, false);
}

// --- Challenge Agent Finding: vendor slug SQL-injection guard ---
try {
  await ensureVendorStmtTable("x (y int); DROP TABLE extracted_document; --");
  check('Malicious vendor slug is rejected before DDL construction', false);
} catch (e) {
  check(`Malicious vendor slug is rejected before DDL construction — ${e.message}`, /Invalid vendor slug/.test(e.message));
}
try {
  assertValidVendorSlug('keystone');
  check('Valid vendor slug (keystone) passes the guard', true);
} catch (e) {
  check(`Valid vendor slug (keystone) passes the guard (${e.message})`, false);
}
// Confirm extracted_document survived the injection attempt above.
const survivorCount = db.prepare('SELECT COUNT(*) AS n FROM extracted_document').get();
check(`extracted_document table still exists after the injection attempt (${survivorCount.n} rows)`, survivorCount.n > 0);

await closeDb();

if (failures > 0) {
  console.error(`\n${failures} test case(s) FAILED.`);
  process.exit(1);
}
console.log('\nAll Task 1.2 test cases PASS (SQLite).');
