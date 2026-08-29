import { getSqliteDb, getDbMode } from './db';
import { getDocumentById, resolveVendorSlug } from './documents';
import { computeDocumentStatus } from './documentStatus';
import { getExtractionMethodSummary } from './extractionMethodSummary';

/**
 * Document Detail screen data (Task 6.5) — a document's header info, extraction-method
 * summary (Task 3.5), and its extracted StatementLine rows. Confidence/provider are
 * attempt-level, not line-level (extracted.extraction_attempt, not silver.statement_line)
 * — every line a document has came from its one successful attempt (the idempotency guard
 * in extractionPipeline.ts ensures at most one), so a correlated subquery picking that
 * attempt's own confidence/provider describes every line correctly.
 */

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('documentDetail.ts only supports the local SQLite fallback — Fabric required starting Session 4/5.');
  }
}

export type StatementLineRow = {
  lineId: string;
  invoiceRef: string | null;
  amount: number;
  confidence: number | null;
  providerUsed: string | null;
};

function getStatementLinesForDocument(documentId: string): StatementLineRow[] {
  const db = getSqliteDb();
  return db
    .prepare(
      `SELECT
         sl.line_id AS lineId,
         sl.invoice_ref AS invoiceRef,
         sl.amount AS amount,
         (SELECT att.confidence FROM extracted_extraction_attempt att
            WHERE att.document_id = sl.document_id AND att.arithmetic_pass = 1 AND att.structural_pass = 1
            ORDER BY att.attempt_no DESC LIMIT 1) AS confidence,
         (SELECT att.provider_used FROM extracted_extraction_attempt att
            WHERE att.document_id = sl.document_id AND att.arithmetic_pass = 1 AND att.structural_pass = 1
            ORDER BY att.attempt_no DESC LIMIT 1) AS providerUsed
       FROM silver_statement_line sl
       WHERE sl.document_id = ?
       ORDER BY sl.created_at ASC`
    )
    .all(documentId) as StatementLineRow[];
}

export type DocumentDetailData = {
  documentId: string;
  vendorSlug: string | null;
  statementPeriod: string | null;
  status: string;
  statusBadge: { badge: string; label: string };
  extractionMethodSummary: Record<string, number>;
  lines: StatementLineRow[];
};

export function getDocumentDetail(documentId: string): DocumentDetailData | null {
  assertSqliteMode();
  const doc = getDocumentById(documentId);
  if (!doc) return null;

  const { badge, label } = computeDocumentStatus(documentId);
  return {
    documentId: doc.documentId,
    vendorSlug: resolveVendorSlug(doc.vendorId),
    statementPeriod: doc.statementPeriod,
    status: doc.status,
    statusBadge: { badge, label },
    extractionMethodSummary: getExtractionMethodSummary(documentId),
    lines: getStatementLinesForDocument(documentId),
  };
}
