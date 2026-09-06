import { getSqliteDb, getDbMode } from './db';
import { runExtractionPipeline, SilverNormalizationFailure, RecoveryAttemptsExhausted } from './extractionPipeline';

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

// ENH-001 Task 2.1 (IC-CANDIDATE-01/R-005): a document whose latest attempt already
// passed validation (arithmetic_pass=1, structural_pass=1) but has zero Silver rows is
// stuck exactly in the gap this task fixes — extraction succeeded, normalization never
// completed. Decided here, not in extractionPipeline.ts, since it's what determines HOW
// this trigger invokes the pipeline (skipSuccessGuard or not), not something the pipeline
// itself needs to know on an ordinary fresh call.
function needsSilverRecovery(documentId: string): boolean {
  const db = getSqliteDb();
  const latest = db
    .prepare(
      `SELECT arithmetic_pass, structural_pass FROM extracted_extraction_attempt
       WHERE document_id = ? ORDER BY attempt_no DESC LIMIT 1`
    )
    .get(documentId) as { arithmetic_pass: number | null; structural_pass: number | null } | undefined;
  if (!latest || latest.arithmetic_pass !== 1 || latest.structural_pass !== 1) return false;
  const silverCount = (
    db.prepare('SELECT COUNT(*) AS n FROM silver_statement_line WHERE document_id = ?').get(documentId) as {
      n: number;
    }
  ).n;
  return silverCount === 0;
}

export type TriggerExtractionResult =
  | { ok: true; status: string }
  | { ok: false; reason: 'not_found' | 'already_processing' | 'recovery_exhausted' };

export async function triggerExtraction(documentId: string): Promise<TriggerExtractionResult> {
  assertSqliteMode();
  const db = getSqliteDb();

  const exists = db.prepare('SELECT 1 FROM extracted_document WHERE document_id = ?').get(documentId);
  if (!exists) {
    return { ok: false, reason: 'not_found' };
  }

  const recovering = needsSilverRecovery(documentId);

  // G5's enforcement point: atomic guard, not a read-then-write race. If
  // another trigger already flipped status to 'processing' (or beyond),
  // `changes` is 0 and this trigger is rejected outright — never silently
  // re-queued, never a second extraction started. Unchanged by Task 2.1 —
  // the crash-recovery fix below only adds a rollback path after this guard
  // has already succeeded and ownership has been acquired.
  const result = db
    .prepare(`UPDATE extracted_document SET status = 'processing' WHERE document_id = ? AND status != 'processing'`)
    .run(documentId);

  if (result.changes === 0) {
    return { ok: false, reason: 'already_processing' };
  }

  try {
    // Awaited synchronously — this bounded build has no background-job/queue
    // infrastructure (n8n, per Claude.md's Fixed Stack, only orchestrates the
    // monthly Run Creation call, not per-document extraction), and Extract is
    // a deliberate, low-frequency manual trigger, not a high-throughput path.
    // Session 3 replaces what was a no-op stub through Session 2.
    await runExtractionPipeline(documentId, recovering ? { skipSuccessGuard: true } : undefined);
    return { ok: true, status: 'processing' };
  } catch (err) {
    // ENH-001 Task 2.1 (IC-CANDIDATE-01/R-005): previously, any thrown error here left
    // document.status permanently stuck at 'processing' with no rollback. Reset to
    // 'registered' so a future trigger can re-acquire G5 ownership — the atomic guard's
    // UPDATE above is untouched by this change, only what happens after it succeeds.
    db.prepare(`UPDATE extracted_document SET status = 'registered' WHERE document_id = ?`).run(documentId);

    if (err instanceof RecoveryAttemptsExhausted) {
      // This trigger WAS the recovery attempt and still found no attempt slots left —
      // nothing further to retry. Surfaced distinctly so the caller doesn't report a
      // false "extraction started" success.
      return { ok: false, reason: 'recovery_exhausted' };
    }
    if (err instanceof SilverNormalizationFailure) {
      // Recoverable — status is now 'registered' again, so a future trigger's
      // needsSilverRecovery() check will detect this document and retry with
      // skipSuccessGuard: true automatically. Not reported as a hard failure to the
      // caller; the reset alone is the fix, same as any other retriable state.
      return { ok: true, status: 'registered' };
    }
    throw err; // any other error (e.g. document not found mid-flight) — surfaced, not swallowed
  }
}
