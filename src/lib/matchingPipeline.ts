import { getSqliteDb, getDbMode } from './db';
import { matchStatementLine, writeMatch } from './deterministicMatching';
import type { MatchOutcome } from './deterministicMatching';
import { runResidualMatch } from './aiResidualMatching';
import { writeException } from './exceptionWriter';
import type { ExceptionCategory, ExceptionInput } from './exceptionWriter';

/**
 * Matching pipeline orchestrator — ties Task 5.2 (deterministic matching), 5.3
 * (AI-assisted residual matching), and 5.4 (exception schema wiring) into the single flow
 * Task 5.1's invocation/locking replaces its stub with.
 *
 * Per line: deterministic match first (Task 5.2). A resolved match writes recon.match
 * directly. An unmatched line runs Task 5.3's residual pass for CCC corroboration
 * (proposal-only, never itself resolving the match), then Task 5.4 writes the exception
 * with both stages' evidence.
 *
 * Write ordering (2026-08-31, engineer-directed): all per-line matching work (both async —
 * live Fabric lookups now that deterministicMatching.ts can hit real Fabric — and local)
 * happens first, buffered in memory; every recon.match/recon.exception row for this
 * document is then written together in ONE synchronous transaction at the end. Before
 * this, each line committed individually mid-loop, so a concurrent read (the Exceptions
 * screen open in another tab, Home's stats) could observe a genuinely in-progress
 * document's PARTIAL results — some lines resolved, others not yet reached — which was
 * never visible back when matching was instant against local SQLite fixtures, but became
 * a real, user-facing problem once each line's match involves an actual network round
 * trip. Now a concurrent reader sees either none of this document's results or all of
 * them, never a partial slice.
 */

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('matchingPipeline.ts only supports the local SQLite fallback — Fabric required starting Session 5.');
  }
}

type EligibleLine = { lineId: string; normalizedInvoiceRef: string | null; amount: number };

function getEligibleLinesForDocument(documentId: string): EligibleLine[] {
  const db = getSqliteDb();
  const rows = db
    .prepare(
      `SELECT sl.line_id AS lineId, sl.normalized_invoice_ref AS normalizedInvoiceRef, sl.amount AS amount
       FROM silver_statement_line sl
       WHERE sl.document_id = ?
         AND NOT EXISTS (SELECT 1 FROM recon_match m WHERE m.statement_line_id = sl.line_id)
         AND NOT EXISTS (SELECT 1 FROM recon_exception e WHERE e.statement_line_id = sl.line_id)`
    )
    .all(documentId) as EligibleLine[];
  return rows;
}

type PendingWrite =
  | { type: 'match'; lineId: string; reference: NonNullable<MatchOutcome['reference']> }
  | { type: 'exception'; input: ExceptionInput };

export async function runMatchingForDocument(documentId: string): Promise<void> {
  assertSqliteMode();
  const lines = getEligibleLinesForDocument(documentId);

  const pending: PendingWrite[] = [];

  for (const line of lines) {
    const outcome = await matchStatementLine(line);

    if (outcome.status === 'matched') {
      if (!outcome.reference) {
        throw new Error(`runMatchingForDocument: matched outcome for line ${line.lineId} had no reference capture.`);
      }
      pending.push({ type: 'match', lineId: line.lineId, reference: outcome.reference });
      continue;
    }

    const residual = await runResidualMatch(line);
    const category: ExceptionCategory = outcome.reasonCodes.includes('AMOUNT_MISMATCH') ? 'amount_mismatch' : 'not_posted';

    pending.push({
      type: 'exception',
      input: {
        statementLineId: line.lineId,
        category,
        reasonCodes: [...outcome.reasonCodes, ...residual.reasonCodes],
        evidence: { deterministic: outcome.evidence, residual: residual.evidence },
        reference: outcome.reference,
      },
    });
  }

  const db = getSqliteDb();
  const commitAll = db.transaction((writes: PendingWrite[]) => {
    for (const w of writes) {
      if (w.type === 'match') writeMatch(w.lineId, w.reference);
      else writeException(w.input);
    }
  });
  commitAll(pending);
}
