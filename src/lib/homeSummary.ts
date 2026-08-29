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
  extractionFailures: number;
  reconciledCount: number;
  notReconciledCount: number;
};

export function getHomeSummaryStats(): HomeSummaryStats {
  assertSqliteMode();
  const db = getSqliteDb();
  const documents = listDocumentsWithStatusBadge();
  const openExceptions = (db.prepare('SELECT COUNT(*) AS n FROM recon_exception').get() as { n: number }).n;
  const reconciledCount = documents.filter((d) => d.status_badge.badge === 'Reconciled').length;

  return {
    documentsProcessed: documents.length,
    openExceptions,
    extractionFailures: documents.filter((d) => d.status_badge.badge === 'Failed').length,
    reconciledCount,
    notReconciledCount: documents.length - reconciledCount,
  };
}
