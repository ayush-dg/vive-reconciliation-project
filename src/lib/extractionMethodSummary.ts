import { getSqliteDb, getDbMode } from './db';

/**
 * Extraction-method summary (Task 3.5) — per-document counts by
 * provider_used, for Session 6's Document Detail screen to consume.
 */

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('extractionMethodSummary.ts only supports the local SQLite fallback — Fabric required starting Session 4.');
  }
}

export type ExtractionMethodSummary = Record<string, number>;

export function getExtractionMethodSummary(documentId: string): ExtractionMethodSummary {
  assertSqliteMode();
  const db = getSqliteDb();

  // A nonexistent document and a real document with zero attempts would
  // otherwise both silently return {} — the same ambiguity documentStatus.ts
  // (Task 2.3) already guards against for this exact table. Fail loudly
  // instead of a plausible-looking but wrong empty summary.
  const documentExists = db.prepare('SELECT 1 FROM extracted_document WHERE document_id = ?').get(documentId);
  if (!documentExists) {
    throw new Error(`getExtractionMethodSummary: no document found with id "${documentId}".`);
  }

  // provider_used is only NULL for a catastrophic pre-provider-selection
  // failure (extractionPipeline.ts's catch block, before a provider was ever
  // chosen). COALESCE to an explicit "unknown" bucket rather than filtering
  // these rows out — otherwise "zero attempts" and "attempts that failed
  // before extraction even started" render as the identical {} output.
  const rows = db
    .prepare(
      `SELECT COALESCE(provider_used, 'unknown') AS provider_used, COUNT(*) AS n FROM extracted_extraction_attempt
       WHERE document_id = ?
       GROUP BY COALESCE(provider_used, 'unknown')`
    )
    .all(documentId) as { provider_used: string; n: number }[];

  const summary: ExtractionMethodSummary = {};
  for (const row of rows) {
    summary[row.provider_used] = row.n;
  }
  return summary;
}
