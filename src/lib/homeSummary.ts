import { getSqliteDb, getDbMode } from './db';
import { listDocumentsWithStatusBadge } from './documents';

/**
 * Home screen summary stats (Task 6.1). Reuses Task 2.3's computeDocumentStatus (via
 * listDocumentsWithStatusBadge, the same single source of truth Upload's page already
 * uses) rather than re-deriving status from raw attempt data here — badge classification
 * logic stays in one place.
 */

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('homeSummary.ts only supports the local SQLite fallback — Fabric required starting Session 4/5.');
  }
}

export type HomeSummaryStats = {
  documentsProcessed: number;
  openExceptions: number;
  reconciledCount: number;
  notReconciledCount: number;
};

export function getHomeSummaryStats(): HomeSummaryStats {
  assertSqliteMode();
  const db = getSqliteDb();
  const documents = listDocumentsWithStatusBadge();
  const openExceptions = (db.prepare('SELECT COUNT(*) AS n FROM recon_exception').get() as { n: number }).n;
  // Reconciled is a line-level count (parallel to openExceptions above), not a
  // document-level one: every statement line that went through matching lands in
  // exactly one of recon_match (reconciled) or recon_exception (open exception) — never
  // both — so this is simply "lines that did not become an exception."
  const reconciledCount = (db.prepare('SELECT COUNT(*) AS n FROM recon_match').get() as { n: number }).n;
  // Not-reconciled stays document-level: documents with at least one line still short of
  // a full match (i.e. not every line reconciled) — "documents that need review," not a
  // count derived from the old overloaded 'Failed' badge (which conflated a genuine
  // extraction failure with a document that extracted fine but has open exceptions).
  const fullyReconciledDocs = documents.filter((d) => d.status_badge.badge === 'Reconciled').length;

  return {
    documentsProcessed: documents.length,
    openExceptions,
    reconciledCount,
    notReconciledCount: documents.length - fullyReconciledDocs,
  };
}
