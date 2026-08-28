import { getSqliteDb, getDbMode } from './db';
import { runMatchingForDocument } from './matchingPipeline';

/**
 * Matching invocation (Task 5.1) — manual (per-document) and scheduled (batch) entry
 * points, both converging on the same per-document matching execution logic
 * (matchingPipeline.ts's runMatchingForDocument, wired in below — Tasks 5.2/5.3/5.4's
 * real deterministic + AI-assisted + exception-wiring pipeline, replacing this task's own
 * original placeholder no-op, the same Session-2-stub -> Session-3-real-pipeline
 * precedent Task 2.4/3.1 already established for extraction).
 *
 * G5 — a document cannot have multiple active matching owners simultaneously. Acquired
 * via an atomic INSERT into recon.document_lock (the table's own PRIMARY KEY is the
 * guard — a second concurrent acquisition attempt fails the INSERT), released once
 * matching completes (success or failure) so the SAME document can be matched again
 * later. This is a different lock shape from Task 2.4's extraction lock
 * (extracted.document.status), which never releases — matching is a repeatable
 * operation (e.g. re-matched after a later correction), extraction is not.
 * S1 — this module is never imported by documents.ts's registration path (Task 2.2).
 */

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('matchingInvocation.ts only supports the local SQLite fallback — Fabric required starting Session 5.');
  }
}

// Session-2-stub -> Session-3-real-pipeline precedent applied here too: Task 5.2/5.3/5.4
// replaced the placeholder no-op with the real matchingPipeline.ts orchestrator.
const matchDocument = runMatchingForDocument;

// A lock abandoned by a hard process crash between acquire and release (the only way
// one can be abandoned — a thrown exception is already handled by triggerMatching-
// ForDocument/runScheduledMatchingBatch's own try/finally) would otherwise be permanent:
// nothing ever read acquired_at, so the document could never be matched again without
// manual DB intervention. A lock older than this is treated as abandoned and reclaimable.
const LOCK_STALE_AFTER_MINUTES = 10;

/** Exported for Task 5.1's own dedicated G5 test. The single atomic UPSERT is the entire
 * enforcement mechanism — no interleaving window exists within one Node process for a
 * "more concurrent" test to additionally expose (better-sqlite3 is fully synchronous),
 * the same reasoning that made Task 2.4's sequential-call G5 test sufficient for its own
 * atomic guard. Unlike a plain INSERT-and-catch-the-conflict approach, this can't
 * conflate a genuine lock conflict with an unrelated DB error (a non-conflict failure
 * here throws, rather than silently reporting "already held"). */
export function acquireMatchingLock(documentId: string): boolean {
  const db = getSqliteDb();
  const result = db
    .prepare(
      `INSERT INTO recon_document_lock (document_id, acquired_at) VALUES (?, datetime('now'))
       ON CONFLICT(document_id) DO UPDATE SET acquired_at = excluded.acquired_at
       WHERE recon_document_lock.acquired_at < datetime('now', ?)`
    )
    .run(documentId, `-${LOCK_STALE_AFTER_MINUTES} minutes`);
  return result.changes === 1;
}

export function releaseMatchingLock(documentId: string): void {
  const db = getSqliteDb();
  db.prepare(`DELETE FROM recon_document_lock WHERE document_id = ?`).run(documentId);
}

export type TriggerMatchingResult =
  | { ok: true }
  | { ok: false; reason: 'not_found' | 'already_processing' };

/** Manual path — Task 6.1's per-document "Reconcile" button calls this via its API route. */
export async function triggerMatchingForDocument(documentId: string): Promise<TriggerMatchingResult> {
  assertSqliteMode();
  const db = getSqliteDb();

  const exists = db.prepare('SELECT 1 FROM extracted_document WHERE document_id = ?').get(documentId);
  if (!exists) {
    return { ok: false, reason: 'not_found' };
  }

  if (!acquireMatchingLock(documentId)) {
    return { ok: false, reason: 'already_processing' };
  }

  try {
    await matchDocument(documentId);
  } finally {
    releaseMatchingLock(documentId);
  }

  return { ok: true };
}

/** Documents with at least one silver.statement_line row that has neither a Match nor an
 * Exception yet — i.e. never processed by matching. Used by the scheduled batch path; the
 * manual path already knows its target document_id from the caller. */
function getEligibleDocumentIds(): string[] {
  const db = getSqliteDb();
  const rows = db
    .prepare(
      `SELECT DISTINCT sl.document_id AS document_id
       FROM silver_statement_line sl
       WHERE NOT EXISTS (SELECT 1 FROM recon_match m WHERE m.statement_line_id = sl.line_id)
         AND NOT EXISTS (SELECT 1 FROM recon_exception e WHERE e.statement_line_id = sl.line_id)`
    )
    .all() as { document_id: string }[];
  return rows.map((r) => r.document_id);
}

export type ScheduledMatchingBatchResult = {
  processed: string[];
  skipped: string[]; // already locked by a concurrent invocation (manual or another batch run)
};

/** Scheduled path — no live timer/cron infrastructure invokes this in this build (see
 * sessions/S05_SESSION_LOG.md's Decision Log); exposed as a callable function and a thin
 * API route so an external scheduler can invoke it. */
export async function runScheduledMatchingBatch(): Promise<ScheduledMatchingBatchResult> {
  assertSqliteMode();
  const processed: string[] = [];
  const skipped: string[] = [];

  for (const documentId of getEligibleDocumentIds()) {
    if (!acquireMatchingLock(documentId)) {
      skipped.push(documentId);
      continue;
    }
    try {
      await matchDocument(documentId);
      processed.push(documentId);
    } finally {
      releaseMatchingLock(documentId);
    }
  }

  return { processed, skipped };
}
