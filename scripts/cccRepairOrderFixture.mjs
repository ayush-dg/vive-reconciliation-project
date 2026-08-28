// Test-only fixture for CCC repair-order data (Task 5.3). Unlike bronze.netsuite_vendorbill
// (engineer-confirmed by direct inspection, ARCHITECTURE.md D-M), CCC's real table name is
// NOT confirmed — D9/D-M name it only as "equivalent CCC tables." `bronze_ccc_repair_order`
// is this project's own placeholder name, not a verified production name. Task 5.3's own
// spec frames CCC corroboration as "where available," and aiResidualMatching.ts degrades
// to "no corroboration available" if a query against this name fails (e.g. because the
// real table has a different name) — so this fixture exists purely to exercise that
// corroboration-found code path in tests, not to assert what the real schema is.
import { getSqliteDb } from '../src/lib/db.ts';

export function ensureCccRepairOrderFixtureTable() {
  const db = getSqliteDb();
  db.exec(`
    CREATE TABLE IF NOT EXISTS bronze_ccc_repair_order (
      ro_number       TEXT     NOT NULL PRIMARY KEY,
      vendor_name     TEXT     NOT NULL,
      amount          NUMERIC  NOT NULL,
      _run_id         TEXT     NOT NULL,
      _extracted_at   TEXT     NOT NULL,
      _source_system  TEXT     NOT NULL
    )
  `);
}

export function seedCccRepairOrderRow(db, { roNumber, vendorName, amount, runId, extractedAt, sourceSystem = 'ccc_one' }) {
  db.prepare(
    `INSERT INTO bronze_ccc_repair_order (ro_number, vendor_name, amount, _run_id, _extracted_at, _source_system)
     VALUES (?, ?, ?, ?, ?, ?)`
  ).run(roNumber, vendorName, amount, runId, extractedAt, sourceSystem);
}
