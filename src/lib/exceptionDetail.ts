import { getSqliteDb, getDbMode } from './db';

/**
 * Exception Detail (Task 6.3). CCC corroborating evidence and the amount-mismatch
 * drill-down both read from `recon.exception.evidence` (captured at match time — Task
 * 5.2/5.3, ARCHITECTURE.md D-M) — never a live re-query, and never `silver.ccc_ro` (a
 * Silver transform this project doesn't build; UI_SURFACE.md's line naming it is a stale
 * cross-reference, already flagged in sessions/S05_SESSION_LOG.md's Out of Scope
 * Observations — this module reads the mechanism this project actually built instead).
 */

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('exceptionDetail.ts only supports the local SQLite fallback — Fabric required starting Session 4/5.');
  }
}

export type CccEvidence = { roNumber: string; amount: number } | null;
export type AmountMismatchEvidence = { statementAmount: number; netsuiteAmount: number } | null;
export type ExceptionStatus = 'open' | 'resolved' | 'flagged' | 'skipped';

export type ExceptionDetailData = {
  exceptionId: string;
  category: string;
  status: ExceptionStatus;
  note: string | null;
  resolvedAt: string | null;
  createdAt: string;
  referenceExtractedAt: string | null;
  statementLine: {
    lineId: string;
    invoiceRef: string | null;
    amount: number;
    documentId: string;
    vendorSlug: string | null;
    statementPeriod: string | null;
  };
  cccCorroboration: CccEvidence;
  amountMismatch: AmountMismatchEvidence;
  // Full raw NetSuite bill/credit row captured at match time (fabricLakehouse.ts,
  // 2026-09-01) — null against the local SQLite fixture (no such data exists there) or
  // for a not_posted exception (nothing was found to capture).
  netsuiteRecord: Record<string, unknown> | null;
};

export function getExceptionDetail(exceptionId: string): ExceptionDetailData | null {
  assertSqliteMode();
  const db = getSqliteDb();
  const row = db
    .prepare(
      `SELECT
         e.exception_id AS exceptionId,
         e.category AS category,
         e.status AS status,
         e.note AS note,
         e.resolved_at AS resolvedAt,
         e.created_at AS createdAt,
         e.evidence AS evidence,
         e.reference_extracted_at AS referenceExtractedAt,
         sl.line_id AS lineId,
         sl.invoice_ref AS invoiceRef,
         sl.amount AS amount,
         sl.document_id AS documentId,
         d.statement_period AS statementPeriod,
         vr.vendor_slug AS vendorSlug
       FROM recon_exception e
       JOIN silver_statement_line sl ON sl.line_id = e.statement_line_id
       JOIN extracted_document d ON d.document_id = sl.document_id
       LEFT JOIN extracted_vendor_registry vr ON vr.vendor_id = sl.vendor_id
       WHERE e.exception_id = ?`
    )
    .get(exceptionId) as
    | {
        exceptionId: string;
        category: string;
        status: ExceptionStatus;
        note: string | null;
        resolvedAt: string | null;
        createdAt: string;
        evidence: string;
        referenceExtractedAt: string | null;
        lineId: string;
        invoiceRef: string | null;
        amount: number;
        documentId: string;
        statementPeriod: string | null;
        vendorSlug: string | null;
      }
    | undefined;

  if (!row) return null;

  let evidence: Record<string, unknown> = {};
  // evidence is a nullable column (migration 005) — JSON.parse(null) doesn't throw (it
  // string-coerces to "null" and returns JS null), so a NULL row would silently bypass
  // this try/catch and throw uncaught on evidence.residual/evidence.deterministic below.
  // Guarded explicitly rather than relying on the catch to cover every malformed case.
  if (row.evidence) {
    try {
      evidence = JSON.parse(row.evidence);
    } catch {
      // Leave empty — a malformed evidence blob degrades to "no evidence shown", not a crash.
    }
  }

  const residual = evidence.residual as { cccCorroboration?: { roNumber: string; amount: number } } | undefined;
  const cccCorroboration: CccEvidence = residual?.cccCorroboration
    ? { roNumber: residual.cccCorroboration.roNumber, amount: residual.cccCorroboration.amount }
    : null;

  const deterministic = evidence.deterministic as
    | { statementAmount?: number; netsuiteAmount?: number; netsuiteRecord?: Record<string, unknown> | null }
    | undefined;
  const amountMismatch: AmountMismatchEvidence =
    row.category === 'amount_mismatch' && deterministic?.statementAmount !== undefined && deterministic?.netsuiteAmount !== undefined
      ? { statementAmount: deterministic.statementAmount, netsuiteAmount: deterministic.netsuiteAmount }
      : null;

  return {
    exceptionId: row.exceptionId,
    category: row.category,
    status: row.status,
    note: row.note,
    resolvedAt: row.resolvedAt,
    createdAt: row.createdAt,
    referenceExtractedAt: row.referenceExtractedAt,
    statementLine: {
      lineId: row.lineId,
      invoiceRef: row.invoiceRef,
      amount: row.amount,
      documentId: row.documentId,
      vendorSlug: row.vendorSlug,
      statementPeriod: row.statementPeriod,
    },
    cccCorroboration,
    amountMismatch,
    netsuiteRecord: deterministic?.netsuiteRecord ?? null,
  };
}

const VALID_STATUSES: ExceptionStatus[] = ['open', 'resolved', 'flagged', 'skipped'];

/** The single write path for recon.exception's resolution workflow — Mark
 * resolved/Flag for vendor/Skip, plus the optional note. Engineer-directed deviation
 * from ARCHITECTURE.md D-C (see this module's doc comment via exceptionsList.ts). */
export function updateExceptionResolution(
  exceptionId: string,
  input: { status: ExceptionStatus; note?: string | null }
): void {
  assertSqliteMode();
  if (!VALID_STATUSES.includes(input.status)) {
    throw new Error(`updateExceptionResolution: unrecognized status "${input.status}".`);
  }
  const db = getSqliteDb();
  const resolvedAt = input.status === 'open' ? null : new Date().toISOString();
  const result = db
    .prepare(
      `UPDATE recon_exception SET status = ?, note = COALESCE(?, note), resolved_at = ? WHERE exception_id = ?`
    )
    .run(input.status, input.note ?? null, resolvedAt, exceptionId);
  if (result.changes === 0) {
    throw new Error(`updateExceptionResolution: no exception found with id "${exceptionId}".`);
  }
}
