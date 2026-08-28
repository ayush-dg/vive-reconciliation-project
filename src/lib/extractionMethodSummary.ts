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
  const rows = db
    .prepare(
      `SELECT provider_used, COUNT(*) AS n FROM extracted_extraction_attempt
       WHERE document_id = ? AND provider_used IS NOT NULL
       GROUP BY provider_used`
    )
    .all(documentId) as { provider_used: string; n: number }[];

  const summary: ExtractionMethodSummary = {};
  for (const row of rows) {
    summary[row.provider_used] = row.n;
  }
  return summary;
}
