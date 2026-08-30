import crypto from 'node:crypto';
import { getSqliteDb, getDbMode } from './db';
import { isFabricLakehouseConfigured, getReferenceRowByTranId, getLatestReferenceWatermark as getLiveLatestReferenceWatermark } from './fabricLakehouse';

/**
 * Deterministic SQL-based matching (Task 5.2). Recon key: vendor invoice number
 * (silver.statement_line.normalized_invoice_ref) matched to NetSuite's Bill document
 * number — the real bronze.netsuite_vendorbill column is `tranid`, confirmed by direct
 * Lakehouse inspection (engineer-confirmed 2026-08-30, not the fixture's invented
 * `bill_document_number` name). Reads bronze.netsuite_vendorbill directly — the
 * externally-owned Lakehouse table (ARCHITECTURE.md D-M), NOT the similarly-named but
 * incorrect bronze.netsuite_netsuite_vendorbill. No separate Silver copy of this data is
 * built.
 *
 * Live vs. local fixture: when isFabricLakehouseConfigured() is true (FABRIC_CLIENT_ID/
 * SECRET/TENANT_ID + FABRIC_LAKEHOUSE_SQL_ENDPOINT/NAME all set — see fabricLakehouse.ts),
 * this reads the real Lakehouse table over the network. Otherwise it falls back to
 * scripts/netsuiteVendorBillFixture.ts's same-shape local SQLite stand-in, which is what
 * every automated test (none of which set those env vars) continues to exercise
 * unchanged. This is a read-only, additive lookup — it does not affect getDbMode() or any
 * other module's SQLite/Fabric switch.
 *
 * S8 (amended) — every reference row read during a match has its
 * _run_id/_extracted_at/_source_system captured onto the Match/Exception created from it,
 * since the source table is upsert-in-place with no retained history. When no matching
 * row is found at all (NOT_POSTED), the reference table's own most-recently-extracted row
 * overall is captured instead, answering "what state of NetSuite data was checked" even
 * though no specific row matched — the docs don't spell out this exact mechanic; recorded
 * as a Scope Decision in sessions/S05_VERIFICATION_RECORD.md. The real live table already
 * carries these same three columns verbatim, confirmed by direct query.
 */

const AMOUNT_TOLERANCE = 0.01;

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('deterministicMatching.ts only supports the local SQLite fallback — Fabric required starting Session 5.');
  }
}

type NormalizedReferenceRow = {
  candidateKey: string;
  refAmount: number;
  _run_id: string;
  _extracted_at: string;
  _source_system: string;
};

type ReferenceCapture = { runId: string; extractedAt: string; sourceSystem: string };

async function findReferenceRowByDocNumber(normalizedInvoiceRef: string): Promise<NormalizedReferenceRow | null> {
  if (isFabricLakehouseConfigured()) {
    const row = await getReferenceRowByTranId(normalizedInvoiceRef);
    if (!row) return null;
    return { candidateKey: row.tranid, refAmount: row.total, _run_id: row._run_id, _extracted_at: row._extracted_at, _source_system: row._source_system };
  }

  const db = getSqliteDb();
  // normalizedInvoiceRef is already trimmed+uppercased (silverNormalization.ts); apply the
  // same normalization to bill_document_number on the read side so a real-world casing or
  // whitespace difference in the source data doesn't silently produce a false NOT_POSTED.
  // bill_document_number has no uniqueness constraint (the reference table's PK is
  // transaction_id) — ORDER BY _extracted_at DESC makes the choice among duplicates
  // deterministic (most-recently-extracted wins) rather than arbitrary.
  const row = db
    .prepare(
      `SELECT bill_document_number AS candidateKey, amount AS refAmount, _run_id, _extracted_at, _source_system
       FROM bronze_netsuite_vendorbill
       WHERE UPPER(TRIM(bill_document_number)) = ?
       ORDER BY _extracted_at DESC LIMIT 1`
    )
    .get(normalizedInvoiceRef) as NormalizedReferenceRow | undefined;
  return row ?? null;
}

/** The reference table's own most-recently-extracted row overall — captured for a
 * NOT_POSTED exception (nothing matched, so there is no specific row to attribute the
 * capture to) so the exception still records what state of NetSuite data was checked. */
async function findLatestReferenceWatermark(): Promise<ReferenceCapture | null> {
  if (isFabricLakehouseConfigured()) {
    const row = await getLiveLatestReferenceWatermark();
    if (!row) return null;
    return { runId: row._run_id, extractedAt: row._extracted_at, sourceSystem: row._source_system };
  }

  const db = getSqliteDb();
  const row = db
    .prepare(
      `SELECT _run_id, _extracted_at, _source_system FROM bronze_netsuite_vendorbill
       ORDER BY _extracted_at DESC LIMIT 1`
    )
    .get() as { _run_id: string; _extracted_at: string; _source_system: string } | undefined;
  if (!row) return null;
  return { runId: row._run_id, extractedAt: row._extracted_at, sourceSystem: row._source_system };
}

export type MatchOutcome = {
  stage: 'deterministic_match';
  status: 'matched' | 'unmatched';
  candidateIds: string[];
  reasonCodes: string[];
  evidence: Record<string, unknown>;
  requiresReview: boolean;
  reference: ReferenceCapture | null;
};

export async function matchStatementLine(line: {
  normalizedInvoiceRef: string | null;
  amount: number;
}): Promise<MatchOutcome> {
  if (!line.normalizedInvoiceRef) {
    // Defensive only — Task 3.2's validation gate already guarantees invoice_ref or
    // ro_number is present before a line reaches Silver; not reachable in practice, but
    // the column is nullable at the schema level.
    return {
      stage: 'deterministic_match',
      status: 'unmatched',
      candidateIds: [],
      reasonCodes: ['NOT_POSTED'],
      evidence: { reason: 'no invoice reference to match against' },
      requiresReview: true,
      reference: await findLatestReferenceWatermark(),
    };
  }

  const ref = await findReferenceRowByDocNumber(line.normalizedInvoiceRef);
  if (!ref) {
    return {
      stage: 'deterministic_match',
      status: 'unmatched',
      candidateIds: [],
      reasonCodes: ['NOT_POSTED'],
      evidence: { normalizedInvoiceRef: line.normalizedInvoiceRef },
      requiresReview: true,
      reference: await findLatestReferenceWatermark(),
    };
  }

  const reference: ReferenceCapture = { runId: ref._run_id, extractedAt: ref._extracted_at, sourceSystem: ref._source_system };
  const diff = Math.abs(line.amount - ref.refAmount);

  if (diff > AMOUNT_TOLERANCE) {
    return {
      stage: 'deterministic_match',
      status: 'unmatched',
      candidateIds: [ref.candidateKey],
      reasonCodes: ['AMOUNT_MISMATCH'],
      evidence: { statementAmount: line.amount, netsuiteAmount: ref.refAmount, diff },
      requiresReview: true,
      reference,
    };
  }

  return {
    stage: 'deterministic_match',
    status: 'matched',
    candidateIds: [ref.candidateKey],
    reasonCodes: [],
    evidence: { statementAmount: line.amount, netsuiteAmount: ref.refAmount },
    requiresReview: false,
    reference,
  };
}

/** Writes a recon.match row for a resolved deterministic match — the only place this
 * table is written from (Task 5.2 owns Match writes; Task 5.4 owns Exception writes for
 * the unmatched case). All 3 reference columns are NOT NULL at the schema level, matching
 * the requirement that every Match traces to a specific reference-data state. */
export function writeMatch(statementLineId: string, reference: ReferenceCapture): void {
  assertSqliteMode();
  const db = getSqliteDb();
  db.prepare(
    `INSERT INTO recon_match (match_id, statement_line_id, reference_run_id, reference_extracted_at, reference_source_system)
     VALUES (?, ?, ?, ?, ?)`
  ).run(crypto.randomUUID(), statementLineId, reference.runId, reference.extractedAt, reference.sourceSystem);
}
