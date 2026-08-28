import { getSqliteDb, getDbMode } from './db';
import { runExtractionPipeline } from './extractionPipeline';

/**
 * Extract trigger (Task 2.4) — D-I: extraction is a separate, explicit user
 * act from upload, never reachable from the registration code path (Task
 * 2.2). G5: atomic processing-ownership acquisition before invoking the
 * extraction service — the status transition to 'processing' IS the
 * ownership acquisition, guarded by a single `WHERE status != 'processing'`
 * UPDATE so two concurrent triggers can never both proceed.
 */

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('extraction.ts only supports the local SQLite fallback — Fabric required starting Session 4.');
  }
}

export type TriggerExtractionResult =
  | { ok: true; status: string }
  | { ok: false; reason: 'not_found' | 'already_processing' };

export async function triggerExtraction(documentId: string): Promise<TriggerExtractionResult> {
  assertSqliteMode();
  const db = getSqliteDb();

  const exists = db.prepare('SELECT 1 FROM extracted_document WHERE document_id = ?').get(documentId);
  if (!exists) {
    return { ok: false, reason: 'not_found' };
  }

  // G5's enforcement point: atomic guard, not a read-then-write race. If
  // another trigger already flipped status to 'processing' (or beyond),
  // `changes` is 0 and this trigger is rejected outright — never silently
  // re-queued, never a second extraction started.
  const result = db
    .prepare(`UPDATE extracted_document SET status = 'processing' WHERE document_id = ? AND status != 'processing'`)
    .run(documentId);

  if (result.changes === 0) {
    return { ok: false, reason: 'already_processing' };
  }

  // Awaited synchronously — this bounded build has no background-job/queue
  // infrastructure (n8n, per Claude.md's Fixed Stack, only orchestrates the
  // monthly Run Creation call, not per-document extraction), and Extract is
  // a deliberate, low-frequency manual trigger, not a high-throughput path.
  // Session 3 replaces what was a no-op stub through Session 2.
  await runExtractionPipeline(documentId);
  return { ok: true, status: 'processing' };
}
