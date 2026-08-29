import { getSqliteDb, getDbMode } from './db';

/**
 * Exceptions list (Task 6.2) — vendor/statement/invoice-ref/amount/type/date, per
 * UI_SURFACE.md's List Configuration. Pagination: 50/page (resolved default). Search:
 * vendor and invoice ref fields only (resolved default) — no richer search, per D-A's
 * flat-list scope. No possible_duplicate_correction category exists to filter (Task 5.4's
 * enum never included it — D-H's version-chaining resolves that case before Exceptions).
 */

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('exceptionsList.ts only supports the local SQLite fallback — Fabric required starting Session 4/5.');
  }
}

// SQLite's LIKE treats % and _ as wildcards — vendor_slug values are underscore-delimited
// by construction (vendorIdentification.ts's slugify()), so an unescaped search for e.g.
// "fred_beans" would let the "_" match any single character, silently broadening the
// match beyond the literal typed string. Escaped here and matched with ESCAPE '\' below.
function escapeLikePattern(value: string): string {
  return value.replace(/[\\%_]/g, (ch) => `\\${ch}`);
}

export const EXCEPTIONS_PAGE_SIZE = 50;

export type ExceptionListRow = {
  exceptionId: string;
  vendorSlug: string | null;
  documentId: string;
  statementPeriod: string | null;
  invoiceRef: string | null;
  amount: number;
  category: string;
  createdAt: string;
};

export type ExceptionsListResult = {
  rows: ExceptionListRow[];
  total: number;
  page: number;
  pageSize: number;
};

export function listExceptions(options: { search?: string; page?: number } = {}): ExceptionsListResult {
  assertSqliteMode();
  const db = getSqliteDb();
  const page = Math.max(1, options.page ?? 1);
  const offset = (page - 1) * EXCEPTIONS_PAGE_SIZE;

  const search = options.search?.trim();
  const searchClause = search ? `AND (vr.vendor_slug LIKE ? ESCAPE '\\' OR sl.invoice_ref LIKE ? ESCAPE '\\')` : '';
  const escapedSearch = search ? escapeLikePattern(search) : '';
  const searchParams = search ? [`%${escapedSearch}%`, `%${escapedSearch}%`] : [];

  const fromClause = `
    FROM recon_exception e
    JOIN silver_statement_line sl ON sl.line_id = e.statement_line_id
    JOIN extracted_document d ON d.document_id = sl.document_id
    LEFT JOIN extracted_vendor_registry vr ON vr.vendor_id = sl.vendor_id
    WHERE 1 = 1 ${searchClause}
  `;

  const total = (db.prepare(`SELECT COUNT(*) AS n ${fromClause}`).get(...searchParams) as { n: number }).n;

  const rows = db
    .prepare(
      `SELECT
         e.exception_id AS exceptionId,
         vr.vendor_slug AS vendorSlug,
         d.document_id AS documentId,
         d.statement_period AS statementPeriod,
         sl.invoice_ref AS invoiceRef,
         sl.amount AS amount,
         e.category AS category,
         e.created_at AS createdAt
       ${fromClause}
       ORDER BY e.created_at DESC
       LIMIT ? OFFSET ?`
    )
    .all(...searchParams, EXCEPTIONS_PAGE_SIZE, offset) as ExceptionListRow[];

  return { rows, total, page, pageSize: EXCEPTIONS_PAGE_SIZE };
}
