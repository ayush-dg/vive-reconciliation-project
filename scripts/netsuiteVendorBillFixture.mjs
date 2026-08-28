// Test-only fixture for bronze.netsuite_vendorbill (Task 5.2). This table is NOT created
// by any file in migrations/ — Claude.md's Section 3 scope boundary is explicit that
// bronze/gold "already exist for live NetSuite data and are not created by this build's
// migrations" (externally owned, ARCHITECTURE.md D-M). In this sandbox there is no live
// Fabric/Lakehouse connectivity, so this fixture creates a same-shape stand-in purely for
// exercising deterministicMatching.ts's own SQL logic in tests — it is not a claim about
// the real table's full business schema (only its 4 confirmed audit columns are real;
// bill_document_number/amount are this project's own inference of the minimum columns
// needed for the documented recon key).
import { getSqliteDb } from '../src/lib/db.ts';

export function ensureNetsuiteVendorBillFixtureTable() {
  const db = getSqliteDb();
  db.exec(`
    CREATE TABLE IF NOT EXISTS bronze_netsuite_vendorbill (
      transaction_id        TEXT     NOT NULL PRIMARY KEY,
      bill_document_number  TEXT     NOT NULL,
      amount                NUMERIC  NOT NULL,
      _run_id               TEXT     NOT NULL,
      _extracted_at         TEXT     NOT NULL,
      _updated_at           TEXT     NOT NULL,
      _source_system        TEXT     NOT NULL
    )
  `);
}

export function seedNetsuiteVendorBillRow(db, { transactionId, billDocumentNumber, amount, runId, extractedAt, sourceSystem = 'netsuite' }) {
  db.prepare(
    `INSERT INTO bronze_netsuite_vendorbill
       (transaction_id, bill_document_number, amount, _run_id, _extracted_at, _updated_at, _source_system)
     VALUES (?, ?, ?, ?, ?, ?, ?)`
  ).run(transactionId, billDocumentNumber, amount, runId, extractedAt, extractedAt, sourceSystem);
}
