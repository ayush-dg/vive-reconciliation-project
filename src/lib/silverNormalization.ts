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

/** Task 8.5 — true when vendor_id + normalized_invoice_ref + amount already
 * exists in silver.statement_line (across ANY document for this vendor, not
 * just this one — the same invoice reappearing on a later, unrelated
 * statement is exactly the case worth flagging). Never checked for a null
 * normalized_invoice_ref — with no invoice/RO number at all, there is no
 * matching key that would make two such lines meaningfully "the same"
 * invoice rather than coincidentally-equal blanks. */
function isDuplicateLine(vendorId: string, normalizedInvoiceRef: string | null, amount: number): boolean {
  if (!normalizedInvoiceRef) return false;
  const db = getSqliteDb();
  const existing = db
    .prepare(
      `SELECT 1 FROM silver_statement_line
       WHERE vendor_id = ? AND normalized_invoice_ref = ? AND amount = ?
       LIMIT 1`
    )
    .get(vendorId, normalizedInvoiceRef, amount);
  return Boolean(existing);
}

/** Writes one silver.statement_line row per extracted line. Caller (the
 * pipeline orchestrator) is responsible for only calling this after
 * confirming the validation gate passed — this function does not re-check
 * that itself, since it has no way to distinguish "eligible, zero lines" from
 * "not called" otherwise; the gating decision belongs to the orchestrator
 * that already has the ValidationResult in hand.
 *
 * Task 8.5 (2026-09-01) — a duplicate (same vendor_id + normalized_invoice_ref
 * + amount already in Silver) is FLAGGED (is_duplicate_line) but still
 * written and still reaches matching exactly like any other row — an
 * engineer-directed design choice, not an accident: diverting it before
 * Silver would change which lines matching/exceptions ever see, which this
 * task deliberately avoids (see migration 009's own doc comment). */
export function normalizeToSilver(documentId: string, vendorId: string, statement: ExtractedStatement): number {
  assertSqliteMode();
  const db = getSqliteDb();

  const insert = db.prepare(
    `INSERT INTO silver_statement_line
       (line_id, document_id, vendor_id, amount, invoice_ref, normalized_invoice_ref, normalization_version, is_duplicate_line)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
  );

  const insertAll = db.transaction((lines: ExtractedStatement['lines']) => {
    for (const line of lines) {
      const amount = line.amount ?? 0; // amount column is NOT NULL — a blank/credit line normalizes to 0, per S11's immutability guarantee applying from this point on, not a business rule about what 0 "means"
      const normalizedInvoiceRef = normalizeInvoiceRef(line.invoiceRef, line.roNumber);
      const isDuplicate = isDuplicateLine(vendorId, normalizedInvoiceRef, amount);
      insert.run(
        crypto.randomUUID(),
        documentId,
        vendorId,
        amount,
        line.invoiceRef,
        normalizedInvoiceRef,
        NORMALIZATION_VERSION,
        isDuplicate ? 1 : 0
      );
    }
  });

  insertAll(statement.lines);
  return statement.lines.length;
}
