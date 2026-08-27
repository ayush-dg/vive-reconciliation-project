import crypto from 'node:crypto';
import { getSqliteDb, getDbMode } from './db';
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
}): DocumentRow {
  return {
    documentId: row.document_id,
    contentSha256: row.content_sha256,
    legalEntityId: row.legal_entity_id,
    vendorId: row.vendor_id,
    statementPeriod: row.statement_period,
    status: row.status,
    uploadTimestamp: row.upload_timestamp,
  };
}

export function findDocumentByHash(contentSha256: string): DocumentRow | null {
  assertSqliteMode();
  const db = getSqliteDb();
  const row = db
    .prepare(
      `SELECT document_id, content_sha256, legal_entity_id, vendor_id, statement_period, status, upload_timestamp
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
 * existing document is returned, no new row, no re-registration. */
export function registerDocument(fileBytes: Buffer, legalEntityId: string): RegisterResult {
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
  db.prepare(
    `INSERT INTO extracted_document (document_id, content_sha256, legal_entity_id)
     VALUES (?, ?, ?)`
  ).run(documentId, contentSha256, legalEntityId);

  return { document: findDocumentByHash(contentSha256)!, duplicate: false };
}

export function listDocuments(): DocumentRow[] {
  assertSqliteMode();
  const db = getSqliteDb();
  const rows = db
    .prepare(
      `SELECT document_id, content_sha256, legal_entity_id, vendor_id, statement_period, status, upload_timestamp
       FROM extracted_document ORDER BY upload_timestamp DESC`
    )
    .all() as Parameters<typeof rowToDocument>[0][];
  return rows.map(rowToDocument);
}

/** Wire shape returned by /api/documents — snake_case, matching the DB
 * column names, so client code and this module agree on one convention
 * instead of silently mismatching camelCase (DocumentRow) vs snake_case. */
export type ApiDocument = {
  document_id: string;
  content_sha256: string;
  legal_entity_id: string;
  vendor_id: string | null;
  statement_period: string | null;
  status: string;
  upload_timestamp: string;
};

export function toApiDocument(doc: DocumentRow): ApiDocument {
  return {
    document_id: doc.documentId,
    content_sha256: doc.contentSha256,
    legal_entity_id: doc.legalEntityId,
    vendor_id: doc.vendorId,
    statement_period: doc.statementPeriod,
    status: doc.status,
    upload_timestamp: doc.uploadTimestamp,
  };
}

export function getDocumentById(documentId: string): DocumentRow | null {
  assertSqliteMode();
  const db = getSqliteDb();
  const row = db
    .prepare(
      `SELECT document_id, content_sha256, legal_entity_id, vendor_id, statement_period, status, upload_timestamp
       FROM extracted_document WHERE document_id = ?`
    )
    .get(documentId) as Parameters<typeof rowToDocument>[0] | undefined;
  return row ? rowToDocument(row) : null;
}
