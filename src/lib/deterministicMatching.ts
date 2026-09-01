import crypto from 'node:crypto';
import { getSqliteDb, getDbMode } from './db';
import {
  isFabricLakehouseConfigured,
  getReferenceRowByTranId,
  getCreditRowByTranId,
  getLatestReferenceWatermark as getLiveLatestReferenceWatermark,
} from './fabricLakehouse';

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
  // true when this row came from bronze.netsuite_vendorcredit, not vendorbill — NetSuite
  // stores a credit's total as a positive magnitude, while the statement shows the same
  // amount as negative (confirmed 2026-08-31 against 4 real KSI credit-memo lines); the
  // sign has to be flipped before comparing against the statement line's own amount.
  isCredit: boolean;
  _run_id: string;
  _extracted_at: string;
  _source_system: string;
  // Every column of the live NetSuite row, for the Exceptions screen's "NetSuite record"
  // panel — null against the local SQLite fixture, which only carries 4 real columns
  // (no such thing as "the full raw record" exists there to show).
  rawFields: Record<string, unknown> | null;
};

type ReferenceCapture = { runId: string; extractedAt: string; sourceSystem: string };

/** The first name-token of a vendor_slug (e.g. "fred" from "fred_beans_ford_of_
 * mechanicsburg") — used to scope the NetSuite lookup to just that vendor's family of
 * entities. Deliberately just the first token, not several: dealer/vendor group names are
 * reliably identified by their leading word in practice (confirmed 2026-08-31 against
 * real data — "bald hill%"/"fred beans%" both correctly isolate their own family with no
 * false negatives), and a single-token prefix is far less likely to accidentally exclude
 * the real entity than guessing how many words belong to "the brand" for an
 * unfamiliar vendor name shape. */
function vendorNamePrefixFromSlug(vendorSlug: string | null): string | null {
  if (!vendorSlug) return null;
  const firstToken = vendorSlug.split('_')[0];
  return firstToken || null;
}

async function findReferenceRowByDocNumber(
  normalizedInvoiceRef: string,
  vendorSlug: string | null,
  amount: number
): Promise<NormalizedReferenceRow | null> {
  if (isFabricLakehouseConfigured()) {
    const vendorNamePrefix = vendorNamePrefixFromSlug(vendorSlug);
    const row = await getReferenceRowByTranId(normalizedInvoiceRef, vendorNamePrefix, amount);
    if (row) {
      return { candidateKey: row.tranid, refAmount: row.total, isCredit: false, _run_id: row._run_id, _extracted_at: row._extracted_at, _source_system: row._source_system, rawFields: row.rawFields };
    }
    // A miss against vendorbill may still be a genuine credit memo, recorded in NetSuite
    // under a separate table (see fabricLakehouse.ts's getCreditRowByTranId doc comment).
    // Tried second, not first/instead — most lines are ordinary bills, and this keeps
    // that common case at one lookup, not two.
    const creditRow = await getCreditRowByTranId(normalizedInvoiceRef, vendorNamePrefix, amount);
    if (!creditRow) return null;
    return { candidateKey: creditRow.tranid, refAmount: creditRow.total, isCredit: true, _run_id: creditRow._run_id, _extracted_at: creditRow._extracted_at, _source_system: creditRow._source_system, rawFields: creditRow.rawFields };
  }

  const db = getSqliteDb();
  // normalizedInvoiceRef is already trimmed+uppercased (silverNormalization.ts); apply the
  // same normalization to bill_document_number on the read side so a real-world casing or
  // whitespace difference in the source data doesn't silently produce a false NOT_POSTED.
  // bill_document_number has no uniqueness constraint (the reference table's PK is
  // transaction_id) — ORDER BY closest-amount-first, then _extracted_at DESC, makes the
  // choice among duplicates deterministic AND correct (2026-08-31 — plain most-recent-wins
  // was a real bug once tranid collisions across vendors were confirmed live; this local
  // fixture has no vendor table to scope by, so amount-closest is its only defense) rather
  // than arbitrary.
  const row = db
    .prepare(
      `SELECT bill_document_number AS candidateKey, amount AS refAmount, _run_id, _extracted_at, _source_system
       FROM bronze_netsuite_vendorbill
       WHERE UPPER(TRIM(bill_document_number)) = ?
       ORDER BY ABS(amount - ?) ASC, _extracted_at DESC LIMIT 1`
    )
    .get(normalizedInvoiceRef, amount) as Omit<NormalizedReferenceRow, 'isCredit' | 'rawFields'> | undefined;
  // No local fixture equivalent for vendorcredit — the live-only fallback above is what
  // Fabric-configured runs exercise; local/test runs never see a credit-memo match.
  return row ? { ...row, isCredit: false, rawFields: null } : null;
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
  vendorSlug: string | null;
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

  const ref = await findReferenceRowByDocNumber(line.normalizedInvoiceRef, line.vendorSlug, line.amount);
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
  // NetSuite stores a vendor credit's total as a positive magnitude; the statement shows
  // the same amount as negative. Flip the reference's sign before comparing so a genuine
  // credit-memo match isn't reported as a ~2x AMOUNT_MISMATCH.
  const compareAmount = ref.isCredit ? -ref.refAmount : ref.refAmount;
  const diff = Math.abs(line.amount - compareAmount);

  if (diff > AMOUNT_TOLERANCE) {
    return {
      stage: 'deterministic_match',
      status: 'unmatched',
      candidateIds: [ref.candidateKey],
      reasonCodes: ['AMOUNT_MISMATCH'],
      evidence: { statementAmount: line.amount, netsuiteAmount: ref.refAmount, diff, netsuiteRecord: ref.rawFields },
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
