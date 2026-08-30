import { getSqliteDb, getDbMode } from './db';
import { matchStatementLine, writeMatch } from './deterministicMatching';
import { runResidualMatch } from './aiResidualMatching';
import { writeException } from './exceptionWriter';
import type { ExceptionCategory } from './exceptionWriter';

/**
 * Matching pipeline orchestrator — ties Task 5.2 (deterministic matching), 5.3
 * (AI-assisted residual matching), and 5.4 (exception schema wiring) into the single flow
 * Task 5.1's invocation/locking replaces its stub with.
 *
 * Per line: deterministic match first (Task 5.2). A resolved match writes recon.match
 * directly. An unmatched line runs Task 5.3's residual pass for CCC corroboration
 * (proposal-only, never itself resolving the match), then Task 5.4 writes the exception
 * with both stages' evidence.
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

export async function runMatchingForDocument(documentId: string): Promise<void> {
  assertSqliteMode();
  const lines = getEligibleLinesForDocument(documentId);

  for (const line of lines) {
    const outcome = await matchStatementLine(line);

    if (outcome.status === 'matched') {
      if (!outcome.reference) {
        throw new Error(`runMatchingForDocument: matched outcome for line ${line.lineId} had no reference capture.`);
      }
      writeMatch(line.lineId, outcome.reference);
      continue;
    }

    const residual = await runResidualMatch(line);
    const category: ExceptionCategory = outcome.reasonCodes.includes('AMOUNT_MISMATCH') ? 'amount_mismatch' : 'not_posted';

    writeException({
      statementLineId: line.lineId,
      category,
      reasonCodes: [...outcome.reasonCodes, ...residual.reasonCodes],
      evidence: { deterministic: outcome.evidence, residual: residual.evidence },
      reference: outcome.reference,
    });
  }
}
