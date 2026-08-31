import crypto from 'node:crypto';
import { getSqliteDb, getDbMode } from './db';
import { computeDocumentStatus } from './documentStatus';
import { saveDocumentFile } from './storage';

/**
 * Document registration (Task 2.2) — SQLite only for now; Fabric required
 * starting Session 4, same as every other data-access module this session.
 *
 * S1 — this module never calls a matching service, directly or indirectly.
 * G4 — content_sha256 UNIQUE constraint (Task 1.2) is the enforcement point;
 * this function checks first so a duplicate upload is a clean no-op response
 * rather than relying on the DB to throw.
 */

export type DocumentRow = {
  documentId: string;
  contentSha256: string;
  legalEntityId: string;
  vendorId: string | null;
  statementPeriod: string | null;
  status: string;
  uploadTimestamp: string;
  /** The uploaded file's own name (e.g. "lia-statement-july.pdf") — shown on the Upload
   * screen instead of vendor, which is frequently null while extraction is pending/failed
   * and is a separate concept from what file the user actually uploaded. Null for
   * documents registered before this column existed (migration 007) — only
   * content_sha256 was ever stored for those, no filename is recoverable. */
  originalFilename: string | null;
};

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error(
      'documents.ts only supports the local SQLite fallback — Fabric path is not implemented ' +
        'until Session 4 (ARCHITECTURE.md D-J sequencing).'
    );
  }
}

function rowToDocument(row: {
  document_id: string;
  content_sha256: string;
  legal_entity_id: string;
  vendor_id: string | null;
  statement_period: string | null;
  status: string;
  upload_timestamp: string;
  original_filename: string | null;
}): DocumentRow {
  return {
    documentId: row.document_id,
    contentSha256: row.content_sha256,
    legalEntityId: row.legal_entity_id,
    vendorId: row.vendor_id,
    statementPeriod: row.statement_period,
    status: row.status,
    uploadTimestamp: row.upload_timestamp,
    originalFilename: row.original_filename,
  };
}

export function findDocumentByHash(contentSha256: string): DocumentRow | null {
  assertSqliteMode();
  const db = getSqliteDb();
  const row = db
    .prepare(
      `SELECT document_id, content_sha256, legal_entity_id, vendor_id, statement_period, status, upload_timestamp, original_filename
       FROM extracted_document WHERE content_sha256 = ?`
    )
    .get(contentSha256) as Parameters<typeof rowToDocument>[0] | undefined;
  return row ? rowToDocument(row) : null;
}

export type RegisterResult = {
  document: DocumentRow;
  duplicate: boolean;
  /** Set when a duplicate hit's stored legal_entity_id differs from the one
   * just submitted — the submission is still discarded (G4: no second row,
   * no re-registration), but silently dropping a different entity selection
   * with no signal back to the caller would hide a real data-fidelity gap. */
  legalEntityMismatch?: boolean;
};

/** Registers an uploaded PDF. G4: byte-identical uploads are a no-op — the
 * existing document is returned, no new row, no re-registration. originalFilename is
 * best-effort display metadata (Upload screen), not part of the G4 identity/dedup key —
 * a duplicate upload under a different filename still resolves to the existing document
 * unchanged, same as legalEntityMismatch already does for a differing entity. */
export function registerDocument(fileBytes: Buffer, legalEntityId: string, originalFilename: string | null = null): RegisterResult {
  assertSqliteMode();
  const contentSha256 = crypto.createHash('sha256').update(fileBytes).digest('hex');

  const existing = findDocumentByHash(contentSha256);
  if (existing) {
    return {
      document: existing,
      duplicate: true,
      legalEntityMismatch: existing.legalEntityId !== legalEntityId,
    };
  }

  saveDocumentFile(contentSha256, fileBytes);

  const db = getSqliteDb();
  const documentId = crypto.randomUUID();
  try {
    db.prepare(
      `INSERT INTO extracted_document (document_id, content_sha256, legal_entity_id, original_filename)
       VALUES (?, ?, ?, ?)`
    ).run(documentId, contentSha256, legalEntityId, originalFilename);
  } catch (err) {
    // Check-then-insert race: another request registered the same hash
    // between our findDocumentByHash() read and this INSERT (plausible under
    // Claude.md's Azure App Service target, which may run multiple
    // instances). The DB's UNIQUE constraint (Task 1.2, G4) is the real
    // guarantee here — this catch turns that into the same graceful
    // duplicate response the pre-check path returns, not an unhandled 500.
    const isUniqueViolation = err instanceof Error && /UNIQUE constraint failed/i.test(err.message);
    if (!isUniqueViolation) throw err;
    const winner = findDocumentByHash(contentSha256)!;
    return { document: winner, duplicate: true, legalEntityMismatch: winner.legalEntityId !== legalEntityId };
  }

  return { document: findDocumentByHash(contentSha256)!, duplicate: false };
}

export function listDocuments(): DocumentRow[] {
  assertSqliteMode();
  const db = getSqliteDb();
  const rows = db
    .prepare(
      // upload_timestamp has only whole-second resolution (SQLite's datetime('now')) — an
      // upload burst within the same second (real under load, and routinely hit by this
      // project's own test suite writing to the same local DB) ties on that column alone,
      // sorting arbitrarily by document_id instead of actual upload order. rowid is
      // SQLite's own monotonic insertion-order column (still present here since
      // document_id is a TEXT, not INTEGER, primary key) and reliably breaks the tie.
      `SELECT document_id, content_sha256, legal_entity_id, vendor_id, statement_period, status, upload_timestamp, original_filename
       FROM extracted_document ORDER BY upload_timestamp DESC, rowid DESC`
    )
    .all() as Parameters<typeof rowToDocument>[0][];
  return rows.map(rowToDocument);
}

/** Wire shape returned by /api/documents — snake_case, matching the DB
 * column names, so client code and this module agree on one convention
 * instead of silently mismatching camelCase (DocumentRow) vs snake_case.
 *
 * `status` is the raw internal `extracted_document.status` column
 * ('registered' | 'processing', Task 2.4's G5 lock state) — used ONLY to
 * decide whether the Extract action is available. `status_badge` is Task
 * 2.3's computed display badge (Processing/Retrying/Failed/Reconciled) —
 * used for what the user actually sees once extraction has started.
 * Conflating these two was a real defect a challenge-agent pass on Task 2.4
 * found and fixed: the raw column, read directly, can only ever display the
 * literal word "processing" and would never show "Retrying"/"Failed"/
 * "Reconciled" once Session 3's extraction pipeline exists. */
export type ApiDocument = {
  document_id: string;
  content_sha256: string;
  legal_entity_id: string;
  vendor_id: string | null;
  vendor_slug: string | null;
  statement_period: string | null;
  status: string;
  status_badge: { badge: string; label: string };
  upload_timestamp: string;
  original_filename: string | null;
  // Distinguishes the two real, different situations status_badge's 'Failed' value
  // covers (2026-08-31, engineer-directed) — extraction exhausting its retries with
  // nothing to reconcile at all vs. matching having actually run and produced an open
  // exception. Home uses this to show "Done" + a "Show exceptions" link for the latter,
  // reserving a plain "Failed" for a genuine extraction failure.
  open_exception_count: number;
};

/** Human-readable vendor identifier for display (Task 6.1/6.5) — vendor_id is an opaque
 * UUID; extracted.vendor_registry.vendor_slug (e.g. "fred_beans") is what a screen should
 * actually show. Lives here, not documentDetail.ts, since documentDetail.ts already
 * depends on this module (getDocumentById) — a reverse dependency would cycle. */
export function resolveVendorSlug(vendorId: string | null): string | null {
  if (!vendorId) return null;
  const db = getSqliteDb();
  const row = db.prepare('SELECT vendor_slug FROM extracted_vendor_registry WHERE vendor_id = ?').get(vendorId) as
    | { vendor_slug: string }
    | undefined;
  return row?.vendor_slug ?? null;
}

export function getOpenExceptionCount(documentId: string): number {
  const db = getSqliteDb();
  return (
    db
      .prepare(
        `SELECT COUNT(*) AS n FROM recon_exception e
         JOIN silver_statement_line l ON l.line_id = e.statement_line_id
         WHERE l.document_id = ?`
      )
      .get(documentId) as { n: number }
  ).n;
}

export function toApiDocument(
  doc: DocumentRow,
  statusBadge: { badge: string; label: string },
  openExceptionCount: number
): ApiDocument {
  return {
    document_id: doc.documentId,
    content_sha256: doc.contentSha256,
    legal_entity_id: doc.legalEntityId,
    vendor_id: doc.vendorId,
    vendor_slug: resolveVendorSlug(doc.vendorId),
    statement_period: doc.statementPeriod,
    status: doc.status,
    status_badge: statusBadge,
    upload_timestamp: doc.uploadTimestamp,
    original_filename: doc.originalFilename,
    open_exception_count: openExceptionCount,
  };
}

/** Single source of truth for "documents + their Task 2.3 display badge" —
 * used by both the Upload screen's SSR initial render (page.tsx) and the
 * client-side /api/documents refresh path, so the two can't silently drift
 * apart the way DocumentRow (camelCase) vs ApiDocument (snake_case) once did. */
export function listDocumentsWithStatusBadge(): ApiDocument[] {
  return listDocuments().map((doc) => {
    const { badge, label } = computeDocumentStatus(doc.documentId);
    return toApiDocument(doc, { badge, label }, getOpenExceptionCount(doc.documentId));
  });
}

export function getDocumentById(documentId: string): DocumentRow | null {
  assertSqliteMode();
  const db = getSqliteDb();
  const row = db
    .prepare(
      `SELECT document_id, content_sha256, legal_entity_id, vendor_id, statement_period, status, upload_timestamp, original_filename
       FROM extracted_document WHERE document_id = ?`
    )
    .get(documentId) as Parameters<typeof rowToDocument>[0] | undefined;
  return row ? rowToDocument(row) : null;
}
