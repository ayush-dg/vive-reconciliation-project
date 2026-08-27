import { getSqliteDb, getDbMode } from './db';

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

/**
 * Session 3 (not yet built) implements the real extraction pipeline —
 * vendor identification/routing, Claude/pdfplumber extraction, the
 * arithmetic+structural validation gate, bounded retry. This is a stub Task
 * 2.4 wires the G5-guarded trigger through, per Task 2.4's own CC prompt
 * ("call a new extraction-trigger endpoint that invokes Session 3's
 * extraction service"). Intentionally does nothing beyond acknowledging
 * invocation — building the real pipeline here would be Session 3's scope,
 * not this task's.
 */
async function startExtractionPipelineStub(documentId: string): Promise<void> {
  // No-op — see docstring. Session 3 replaces this with the real pipeline.
  void documentId;
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

  await startExtractionPipelineStub(documentId);
  return { ok: true, status: 'processing' };
}
