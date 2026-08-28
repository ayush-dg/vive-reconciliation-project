import crypto from 'node:crypto';
import { getSqliteDb, getDbMode } from './db';

/**
 * Deterministic SQL-based matching (Task 5.2). Recon key: vendor invoice number
 * (silver.statement_line.normalized_invoice_ref) matched to NetSuite's Bill document
 * number, per project convention (not check/payment number). Reads
 * bronze.netsuite_vendorbill directly — the externally-owned Lakehouse table
 * (ARCHITECTURE.md D-M), NOT the similarly-named but incorrect
 * bronze.netsuite_netsuite_vendorbill. No live API call, no separate Silver copy of this
 * data is built.
 *
 * In this sandbox, bronze.netsuite_vendorbill has no real local equivalent (no live
 * Fabric/Lakehouse connectivity) — scripts/netsuiteVendorBillFixture.ts creates a
 * same-shape, test-only stand-in for exercising this module's own SQL logic. In local
 * SQLite mode without that fixture loaded, a query against this table fails loudly with a
 * clear "no such table" error — the honest behavior for data this build doesn't own or
 * mock, not a bug to paper over.
 *
 * S8 (amended) — every reference row read during a match has its
 * _run_id/_extracted_at/_source_system captured onto the Match/Exception created from it,
 * since the source table is upsert-in-place with no retained history. When no matching
 * row is found at all (NOT_POSTED), the reference table's own most-recently-extracted row
 * overall is captured instead, answering "what state of NetSuite data was checked" even
 * though no specific row matched — the docs don't spell out this exact mechanic; recorded
 * as a Scope Decision in sessions/S05_VERIFICATION_RECORD.md.
 */

const AMOUNT_TOLERANCE = 0.01;

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('deterministicMatching.ts only supports the local SQLite fallback — Fabric required starting Session 5.');
  }
}

type ReferenceRow = {
  bill_document_number: string;
  amount: number;
  _run_id: string;
  _extracted_at: string;
  _source_system: string;
};

type ReferenceCapture = { runId: string; extractedAt: string; sourceSystem: string };

function findReferenceRowByDocNumber(normalizedInvoiceRef: string): ReferenceRow | null {
  const db = getSqliteDb();
  // normalizedInvoiceRef is already trimmed+uppercased (silverNormalization.ts); apply the
  // same normalization to bill_document_number on the read side so a real-world casing or
  // whitespace difference in the source data doesn't silently produce a false NOT_POSTED.
  // bill_document_number has no uniqueness constraint (the reference table's PK is
  // transaction_id) — ORDER BY _extracted_at DESC makes the choice among duplicates
  // deterministic (most-recently-extracted wins) rather than arbitrary.
  const row = db
    .prepare(
      `SELECT bill_document_number, amount, _run_id, _extracted_at, _source_system
       FROM bronze_netsuite_vendorbill
       WHERE UPPER(TRIM(bill_document_number)) = ?
       ORDER BY _extracted_at DESC LIMIT 1`
    )
    .get(normalizedInvoiceRef) as ReferenceRow | undefined;
  return row ?? null;
}

/** The reference table's own most-recently-extracted row overall — captured for a
 * NOT_POSTED exception (nothing matched, so there is no specific row to attribute the
 * capture to) so the exception still records what state of NetSuite data was checked. */
function findLatestReferenceWatermark(): ReferenceCapture | null {
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

export function matchStatementLine(line: {
  normalizedInvoiceRef: string | null;
  amount: number;
}): MatchOutcome {
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
      reference: findLatestReferenceWatermark(),
    };
  }

  const ref = findReferenceRowByDocNumber(line.normalizedInvoiceRef);
  if (!ref) {
    return {
      stage: 'deterministic_match',
      status: 'unmatched',
      candidateIds: [],
      reasonCodes: ['NOT_POSTED'],
      evidence: { normalizedInvoiceRef: line.normalizedInvoiceRef },
      requiresReview: true,
      reference: findLatestReferenceWatermark(),
    };
  }

  const reference: ReferenceCapture = { runId: ref._run_id, extractedAt: ref._extracted_at, sourceSystem: ref._source_system };
  const diff = Math.abs(line.amount - ref.amount);

  if (diff > AMOUNT_TOLERANCE) {
    return {
      stage: 'deterministic_match',
      status: 'unmatched',
      candidateIds: [ref.bill_document_number],
      reasonCodes: ['AMOUNT_MISMATCH'],
      evidence: { statementAmount: line.amount, netsuiteAmount: ref.amount, diff },
      requiresReview: true,
      reference,
    };
  }

  return {
    stage: 'deterministic_match',
    status: 'matched',
    candidateIds: [ref.bill_document_number],
    reasonCodes: [],
    evidence: { statementAmount: line.amount, netsuiteAmount: ref.amount },
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
