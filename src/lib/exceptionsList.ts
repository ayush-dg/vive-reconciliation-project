import { getSqliteDb, getDbMode } from './db';

/**
 * Exceptions data layer — vendor-grouped, two-pane master-detail (Exceptions screen
 * redesign, 2026-09-01, engineer-directed, ported from figma3's
 * 05-vive-reconciliation-detail-fredbeans-*.html mockups). Replaces the original flat,
 * all-vendor, paginated list (Task 6.2's D-A-scoped design) — /exceptions is now a
 * per-vendor landing, drilling into /exceptions/[vendorSlug] for that vendor's own
 * exception list + inline detail, matching the mockup's architecture rather than the
 * flat list this build originally shipped.
 *
 * The status/note/resolved_at columns (migration 008) and the resulting "Mark
 * resolved/Flag for vendor/Skip" workflow are themselves an engineer-directed deviation
 * from ARCHITECTURE.md D-C ("this build's exceptions are a flat, ownerless list by
 * design" — no review/approval workspace). Recorded here, not in ARCHITECTURE.md itself
 * (out of this build's edit scope per Claude.md Section 3) — same treatment as
 * documentStatus.ts's 'Reconciling'/'Extracted' badge expansion.
 */

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('exceptionsList.ts only supports the local SQLite fallback — Fabric required starting Session 4/5.');
  }
}

export type VendorExceptionSummary = {
  vendorSlug: string;
  total: number;
  resolvedCount: number;
  missingCount: number;
  mismatchCount: number;
  lastCreatedAt: string;
};

/** One row per vendor that has at least one exception, ordered so vendors with the most
 * unresolved work surface first (all-open vendors before all-resolved ones), then most
 * recent activity. Vendors with a NULL vendor_slug (statement's vendor never resolved) are
 * excluded — there's no meaningful drill-down target for them; a rare state in practice
 * (vendorIdentification.ts resolves a provisional vendor for every extracted line). */
export function listVendorsWithExceptions(): VendorExceptionSummary[] {
  assertSqliteMode();
  const db = getSqliteDb();
  return db
    .prepare(
      `SELECT
         vr.vendor_slug AS vendorSlug,
         COUNT(*) AS total,
         SUM(CASE WHEN e.status != 'open' THEN 1 ELSE 0 END) AS resolvedCount,
         SUM(CASE WHEN e.category = 'not_posted' THEN 1 ELSE 0 END) AS missingCount,
         SUM(CASE WHEN e.category = 'amount_mismatch' THEN 1 ELSE 0 END) AS mismatchCount,
         MAX(e.created_at) AS lastCreatedAt
       FROM recon_exception e
       JOIN silver_statement_line sl ON sl.line_id = e.statement_line_id
       JOIN extracted_vendor_registry vr ON vr.vendor_id = sl.vendor_id
       WHERE vr.vendor_slug IS NOT NULL
       GROUP BY vr.vendor_slug
       ORDER BY (resolvedCount = total) ASC, lastCreatedAt DESC`
    )
    .all() as VendorExceptionSummary[];
}

export type VendorExceptionRow = {
  exceptionId: string;
  invoiceRef: string | null;
  amount: number;
  category: string;
  status: string;
  createdAt: string;
  statementPeriod: string | null;
};

/** Every exception for one vendor, unpaginated — matching the mockup's single scrollable
 * list (`.list-scroll{max-height:640px;overflow-y:auto}`), not a paginated table. A
 * realistic per-vendor reconciliation run's exception count (dozens to low hundreds)
 * never approaches a volume where that tradeoff matters. */
export function listExceptionsForVendor(vendorSlug: string): VendorExceptionRow[] {
  assertSqliteMode();
  const db = getSqliteDb();
  return db
    .prepare(
      `SELECT
         e.exception_id AS exceptionId,
         sl.invoice_ref AS invoiceRef,
         sl.amount AS amount,
         e.category AS category,
         e.status AS status,
         e.created_at AS createdAt,
         d.statement_period AS statementPeriod
       FROM recon_exception e
       JOIN silver_statement_line sl ON sl.line_id = e.statement_line_id
       JOIN extracted_document d ON d.document_id = sl.document_id
       JOIN extracted_vendor_registry vr ON vr.vendor_id = sl.vendor_id
       WHERE vr.vendor_slug = ?
       ORDER BY (e.status != 'open') ASC, e.created_at DESC`
    )
    .all(vendorSlug) as VendorExceptionRow[];
}
