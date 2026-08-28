import crypto from 'node:crypto';
import { getSqliteDb, getDbMode } from './db';

/**
 * Exception category enum + schema wiring (Task 5.4). The single write path for
 * recon.exception — Task 5.2's deterministic no-match and Task 5.3's residual pass both
 * source category/reason_codes/evidence directly from their own structured result
 * (ARCHITECTURE.md D-K) rather than re-deriving it here.
 *
 * S5 — category is a fixed, closed enum (also DB-enforced via a CHECK constraint,
 * Task 1.2) — this module's own runtime check exists so a bad value produces a clear
 * error message rather than a raw SQL constraint error, same defense-in-depth pattern as
 * vendorSchema.ts's assertValidVendorSlug.
 * owner/aging_started_at/run_reference stay NULL — reserved for BCE, never populated here.
 */

const VALID_CATEGORIES = ['amount_mismatch', 'not_posted'] as const;
export type ExceptionCategory = (typeof VALID_CATEGORIES)[number];

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('exceptionWriter.ts only supports the local SQLite fallback — Fabric required starting Session 5.');
  }
}

export type ExceptionInput = {
  statementLineId: string;
  category: ExceptionCategory;
  evidence: Record<string, unknown>;
  // NULL for an exception that never touched reference data (per ARCHITECTURE.md D-M /
  // INVARIANTS.md S8 amended) — populated for a NOT_POSTED/AMOUNT_MISMATCH exception that
  // did.
  reference: { runId: string; extractedAt: string; sourceSystem: string } | null;
};

export function writeException(input: ExceptionInput): void {
  assertSqliteMode();
  if (!VALID_CATEGORIES.includes(input.category)) {
    throw new Error(`writeException: unrecognized category "${input.category}".`);
  }

  const db = getSqliteDb();
  db.prepare(
    `INSERT INTO recon_exception
       (exception_id, statement_line_id, category, reference_run_id, reference_extracted_at, reference_source_system, evidence)
     VALUES (?, ?, ?, ?, ?, ?, ?)`
  ).run(
    crypto.randomUUID(),
    input.statementLineId,
    input.category,
    input.reference?.runId ?? null,
    input.reference?.extractedAt ?? null,
    input.reference?.sourceSystem ?? null,
    JSON.stringify(input.evidence)
  );
}
