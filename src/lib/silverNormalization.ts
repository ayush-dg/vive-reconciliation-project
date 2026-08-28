import crypto from 'node:crypto';
import { getSqliteDb, getDbMode } from './db';
import type { ExtractedStatement } from './aiProvider';

/**
 * extracted -> silver.statement_line normalization (Task 3.6). Only rows
 * belonging to a document whose latest extraction attempt PASSED Task 3.2's
 * validation gate are eligible — a failed document produces zero rows here.
 *
 * S6 — every row is tagged with the normalization logic version that
 * produced it; historical rows are never rewritten when the logic changes,
 * only new rows pick up new versions.
 */

// Bumped only when the normalization LOGIC changes (per S6) — not a general
// app version. v1: initial mapping (extracted line -> statement_line 1:1,
// normalized_invoice_ref = trimmed/uppercased invoice_ref or ro_number).
export const NORMALIZATION_VERSION = 'v1';

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('silverNormalization.ts only supports the local SQLite fallback — Fabric required starting Session 4.');
  }
}

function normalizeInvoiceRef(invoiceRef: string | null, roNumber: string | null): string | null {
  const raw = invoiceRef ?? roNumber;
  return raw ? raw.trim().toUpperCase() : null;
}

/** Writes one silver.statement_line row per extracted line. Caller (the
 * pipeline orchestrator) is responsible for only calling this after
 * confirming the validation gate passed — this function does not re-check
 * that itself, since it has no way to distinguish "eligible, zero lines" from
 * "not called" otherwise; the gating decision belongs to the orchestrator
 * that already has the ValidationResult in hand. */
export function normalizeToSilver(documentId: string, vendorId: string, statement: ExtractedStatement): number {
  assertSqliteMode();
  const db = getSqliteDb();

  const insert = db.prepare(
    `INSERT INTO silver_statement_line
       (line_id, document_id, vendor_id, amount, invoice_ref, normalized_invoice_ref, normalization_version)
     VALUES (?, ?, ?, ?, ?, ?, ?)`
  );

  const insertAll = db.transaction((lines: ExtractedStatement['lines']) => {
    for (const line of lines) {
      insert.run(
        crypto.randomUUID(),
        documentId,
        vendorId,
        line.amount ?? 0, // amount column is NOT NULL — a blank/credit line normalizes to 0, per S11's immutability guarantee applying from this point on, not a business rule about what 0 "means"
        line.invoiceRef,
        normalizeInvoiceRef(line.invoiceRef, line.roNumber),
        NORMALIZATION_VERSION
      );
    }
  });

  insertAll(statement.lines);
  return statement.lines.length;
}
