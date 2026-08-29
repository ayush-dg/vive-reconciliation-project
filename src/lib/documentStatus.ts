import { getSqliteDb, getDbMode } from './db';

/**
 * Status badge computation (Task 2.3) — exposed as a queryable function for
 * Session 6's Home screen to consume; this task only computes and exposes
 * it, per its own description ("the Home screen itself is built in Session
 * 6"). No extraction service exists yet in this session (Session 3), so the
 * function is exercised here against directly-inserted extraction_attempt
 * rows, not a live pipeline.
 *
 * Status values (EXECUTION_PLAN.md Task 2.3, verbatim):
 * "Processing" (no attempts yet or attempt in progress),
 * "Retrying (N/2)" (attempt N failed, retry pending),
 * "Failed — see Exceptions" (OCR_LOW_CONFIDENCE reached),
 * "Reconciled" (matched successfully).
 *
 * Resolving an apparent tension with Task 2.4: Task 2.4's own text says a
 * freshly-registered, not-yet-extracted document's status "remains
 * 'Registered'/pre-Processing until Extract is explicitly clicked." Task
 * 2.3's own literal rule folds "no attempts yet" into the "Processing"
 * badge — there is no fifth "Registered" badge value anywhere in
 * UI_SURFACE.md's fixed four-value set. Read together: "Registered" in Task
 * 2.4 describes the internal extracted.document.status column (used for
 * G5's lock — see documents.ts's future Task 2.4 extension), not a distinct
 * user-facing badge. The badge intentionally treats "not yet triggered" and
 * "triggered, no attempts recorded yet" identically, per Task 2.3's own
 * wording.
 */

export type DocumentStatusBadge = 'Processing' | 'Retrying' | 'Failed' | 'Reconciled';

export type DocumentStatusResult = {
  badge: DocumentStatusBadge;
  label: string; // exact display text, e.g. "Retrying (1/2)"
  attemptCount: number;
};

const MAX_ATTEMPTS = 2; // S7

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('documentStatus.ts only supports the local SQLite fallback — Fabric required starting Session 4.');
  }
}

export function computeDocumentStatus(documentId: string): DocumentStatusResult {
  assertSqliteMode();
  const db = getSqliteDb();

  const documentExists = db.prepare('SELECT 1 FROM extracted_document WHERE document_id = ?').get(documentId);
  if (!documentExists) {
    // A stale/mistyped/deleted document_id would otherwise be indistinguishable
    // from a legitimate, brand-new zero-attempt document (both have zero
    // attempt rows) — fail loudly instead of returning a plausible-looking
    // but wrong "Processing" result.
    throw new Error(`computeDocumentStatus: no document found with id "${documentId}".`);
  }

  const attempts = db
    .prepare(
      `SELECT attempt_no, arithmetic_pass, structural_pass FROM extracted_extraction_attempt
       WHERE document_id = ? ORDER BY attempt_no ASC`
    )
    .all(documentId) as { attempt_no: number; arithmetic_pass: number | null; structural_pass: number | null }[];

  // "Reconciled" — EVERY one of this document's statement lines has a match,
  // not merely "at least one line matched" (amended — Session 6's own Home/
  // Document Detail screens surfaced this as a real defect: a partially-
  // matched document, some lines matched and at least one left as an open
  // exception, was being reported as fully "Reconciled", silently hiding the
  // still-open exception from both the badge and Home's reconciled-count
  // stat). IC-2/G2 guarantee a match can only exist for a document whose
  // latest extraction already passed validation, so trusting recon.match's
  // existence as authoritative is still sound — just now checked for
  // completeness across all lines, not merely presence on any one.
  const totalLines = (
    db.prepare('SELECT COUNT(*) AS n FROM silver_statement_line WHERE document_id = ?').get(documentId) as { n: number }
  ).n;
  const matchedLines = (
    db
      .prepare(
        `SELECT COUNT(*) AS n FROM recon_match m
         JOIN silver_statement_line l ON l.line_id = m.statement_line_id
         WHERE l.document_id = ?`
      )
      .get(documentId) as { n: number }
  ).n;
  if (totalLines > 0 && matchedLines === totalLines) {
    return { badge: 'Reconciled', label: 'Reconciled', attemptCount: attempts.length };
  }

  // A document that has been through matching and has at least one open
  // exception (Task 5.2's no-match/amount-mismatch path, or Task 5.3's
  // residual pass) is surfaced via the same "Failed — see Exceptions" badge
  // extraction failures use — the label's own wording ("see Exceptions")
  // already fits a matching-produced exception exactly as well as an
  // extraction one, and no fifth badge value exists in UI_SURFACE.md's fixed
  // four-value set to invent a distinct one. Checked before the extraction-
  // attempt-based logic below so a document that both retried extraction and
  // later produced a matching exception still correctly reads as needing
  // attention, not silently "Processing".
  const hasOpenException = !!db
    .prepare(
      `SELECT 1 FROM recon_exception e
       JOIN silver_statement_line l ON l.line_id = e.statement_line_id
       WHERE l.document_id = ? LIMIT 1`
    )
    .get(documentId);
  if (hasOpenException) {
    return { badge: 'Failed', label: 'Failed — see Exceptions', attemptCount: attempts.length };
  }

  // Status is driven by the LATEST attempt, not by lifetime failure count —
  // a document whose attempt 1 failed but attempt 2 succeeded (Task 3.3's
  // own stated happy path) must read as "Processing" (matching-eligible,
  // awaiting Reconcile), never stuck showing a "retry pending" label for a
  // retry that already happened and succeeded.
  const latest = attempts.at(-1);
  const latestFailed = latest ? latest.arithmetic_pass === 0 || latest.structural_pass === 0 : false;

  if (!latest || !latestFailed) {
    // No attempts yet, latest attempt still in progress (both pass fields
    // NULL), or latest attempt succeeded — all read as "Processing".
    return { badge: 'Processing', label: 'Processing', attemptCount: attempts.length };
  }

  const failedCount = attempts.filter((a) => a.arithmetic_pass === 0 || a.structural_pass === 0).length;
  if (failedCount >= MAX_ATTEMPTS) {
    return { badge: 'Failed', label: 'Failed — see Exceptions', attemptCount: attempts.length };
  }
  return { badge: 'Retrying', label: `Retrying (${failedCount}/${MAX_ATTEMPTS})`, attemptCount: attempts.length };
}
