-- 001_foundation_schema.sqlite.sql — local SQLite dev equivalent of
-- 001_foundation_schema.sql (Fabric-compatible T-SQL), Task 1.2.
--
-- Why a companion file exists rather than one literal SQL text shared verbatim
-- across both engines: 001_foundation_schema.sql uses `schema.table`-qualified
-- names (extracted.document, silver.statement_line, recon.exception, ...) with
-- FOREIGN KEY constraints spanning those schemas. SQLite has no real multi-schema
-- support inside one file — the only mechanism that accepts literal `schema.table`
-- syntax is ATTACHing separate database files under schema-name aliases, and
-- SQLite explicitly does not enforce foreign keys across attached databases ("the
-- parent and child tables must exist in the same database" — SQLite docs). Since
-- G1 (extraction_attempt FK to document) and the silver->extracted / recon->silver
-- FKs are load-bearing here, an ATTACH-based rendering would silently stop
-- enforcing exactly the constraints this migration exists to enforce.
--
-- This file therefore uses flattened, schema-prefixed table names (extracted_document,
-- silver_statement_line, recon_exception, ...) all living in SQLite's single 'main'
-- schema, so every FK stays same-database and is actually enforced. Every table,
-- column, constraint, and trigger below is the SAME logical schema as
-- 001_foundation_schema.sql — this is the one deliberate, documented dialect fork
-- (table-name qualification syntax), not a second, independently-maintained schema.
-- Keep both files in sync when either changes.
--
-- Applied automatically by src/lib/migrate.ts when FABRIC_SQL_ENDPOINT is unset.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS extracted_vendor_registry (
  vendor_id         TEXT     NOT NULL PRIMARY KEY,
  vendor_slug       TEXT     NOT NULL UNIQUE,
  table_name        TEXT     NOT NULL,
  extraction_route  TEXT     NULL
    CHECK (extraction_route IN ('deterministic', 'claude_primary') OR extraction_route IS NULL),
  created_at        TEXT     NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS extracted_document (
  document_id            TEXT     NOT NULL PRIMARY KEY,
  content_sha256          TEXT     NOT NULL UNIQUE,
  legal_entity_id         TEXT     NOT NULL,
  artifact_type           TEXT     NOT NULL DEFAULT 'vendor_statement',
  vendor_id               TEXT     NULL
    REFERENCES extracted_vendor_registry(vendor_id),
  statement_period        TEXT     NULL,
  status                  TEXT     NOT NULL DEFAULT 'registered',
  version                 INTEGER  NOT NULL DEFAULT 1,
  previous_statement_id   TEXT     NULL
    REFERENCES extracted_document(document_id),
  is_latest_version       INTEGER  NOT NULL DEFAULT 1,
  upload_timestamp        TEXT     NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS extracted_extraction_attempt (
  attempt_id       TEXT     NOT NULL PRIMARY KEY,
  document_id      TEXT     NOT NULL REFERENCES extracted_document(document_id),
  attempt_no       INTEGER  NOT NULL,
  raw_output       TEXT     NULL,
  confidence       REAL     NULL,
  provider_used    TEXT     NULL
    CHECK (provider_used IN ('python_library_pdfplumber', 'claude_sonnet', 'pdfplumber_fallback')
           OR provider_used IS NULL),
  arithmetic_pass  INTEGER  NULL,
  structural_pass  INTEGER  NULL,
  created_at       TEXT     NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS trg_extraction_attempt_no_update
BEFORE UPDATE ON extracted_extraction_attempt
BEGIN
  SELECT RAISE(ABORT, 'extracted.extraction_attempt is append-only; UPDATE is not permitted.');
END;

-- extracted_stmt_<vendor_slug> tables are created at runtime by
-- src/lib/vendorSchema.ts's generator (SQLite branch) — no vendors are known/seeded
-- yet, matching 001_foundation_schema.sql's own note.

CREATE TABLE IF NOT EXISTS silver_statement_line (
  line_id                  TEXT     NOT NULL PRIMARY KEY,
  document_id              TEXT     NOT NULL REFERENCES extracted_document(document_id),
  vendor_id                TEXT     NOT NULL REFERENCES extracted_vendor_registry(vendor_id),
  amount                   NUMERIC  NOT NULL,
  invoice_ref              TEXT     NULL,
  normalized_invoice_ref   TEXT     NULL,
  created_at               TEXT     NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS trg_statement_line_no_amount_update
BEFORE UPDATE OF amount ON silver_statement_line
BEGIN
  SELECT RAISE(ABORT, 'silver.statement_line.amount is immutable after extraction (S11).');
END;

-- See 001_foundation_schema.sql's note on this enum: minimal placeholder, not final.
CREATE TABLE IF NOT EXISTS recon_exception (
  exception_id       TEXT     NOT NULL PRIMARY KEY,
  statement_line_id  TEXT     NOT NULL REFERENCES silver_statement_line(line_id),
  category           TEXT     NOT NULL
    CHECK (category IN ('amount_mismatch', 'not_posted')),
  owner              TEXT     NULL,
  aging_started_at   TEXT     NULL,
  run_reference      TEXT     NULL,
  created_at          TEXT     NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recon_match (
  match_id            TEXT     NOT NULL PRIMARY KEY,
  statement_line_id   TEXT     NOT NULL REFERENCES silver_statement_line(line_id),
  snapshot_version    TEXT     NOT NULL,
  created_at           TEXT     NOT NULL DEFAULT (datetime('now'))
);
