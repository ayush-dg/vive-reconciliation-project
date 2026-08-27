-- 001_foundation_schema.sql — Fabric-compatible T-SQL
-- Task 1.2 (EXECUTION_PLAN.md Session 1): extracted / silver / recon foundation schema.
--
-- This is the CANONICAL migration — the literal file the Verification Command runs
-- via sqlcmd against the live Fabric `recon` SQL database. `bronze`/`silver`/`gold`
-- already host live NetSuite data on Fabric; this migration only creates the new
-- `extracted` schema plus the `silver`/`recon` tables this build owns (it does not
-- touch or recreate any pre-existing NetSuite-derived Silver tables).
--
-- Local SQLite dev (Sessions 1-3) runs 001_foundation_schema.sqlite.sql instead —
-- see that file's header comment for why a companion file exists rather than one
-- literal SQL text shared verbatim across both engines.

CREATE SCHEMA extracted;
GO

-- `silver` and `recon` schemas are assumed to already exist on the live Fabric `recon`
-- SQL database (silver.* hosts existing NetSuite Silver tables; recon is the database
-- itself, per ARCHITECTURE.md D-J/D-B). This migration only creates the new `extracted`
-- schema and the tables listed below within all three — it does not (re)create the
-- `silver`/`recon` schemas themselves. If running against a genuinely fresh database
-- with neither schema provisioned yet, run `CREATE SCHEMA silver;` / `CREATE SCHEMA
-- recon;` first.

-- ============================================================================
-- extracted.vendor_registry
-- Maps vendor_id to its stmt_<vendor_slug> raw table and extraction route.
-- ============================================================================
CREATE TABLE extracted.vendor_registry (
  vendor_id         NVARCHAR(36)   NOT NULL PRIMARY KEY,
  vendor_slug       NVARCHAR(100)  NOT NULL UNIQUE,
  table_name        NVARCHAR(128)  NOT NULL,
  extraction_route  NVARCHAR(20)   NULL
    CHECK (extraction_route IN ('deterministic', 'claude_primary') OR extraction_route IS NULL),
  created_at        DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

-- ============================================================================
-- extracted.document
-- S4: legal_entity_id NOT NULL (DB-enforced).
-- G4: content_sha256 UNIQUE NOT NULL (DB-enforced content-hash idempotency).
-- vendor_id / statement_period NULLABLE — not known at registration; populated by
-- Task 3.1 during extraction (ARCHITECTURE.md D-L amendment).
-- ============================================================================
CREATE TABLE extracted.document (
  document_id            NVARCHAR(36)   NOT NULL PRIMARY KEY,
  content_sha256          NVARCHAR(64)   NOT NULL UNIQUE,
  legal_entity_id         NVARCHAR(36)   NOT NULL,
  artifact_type           NVARCHAR(50)   NOT NULL DEFAULT 'vendor_statement',
  vendor_id               NVARCHAR(36)   NULL
    REFERENCES extracted.vendor_registry(vendor_id),
  statement_period        NVARCHAR(20)   NULL,
  status                  NVARCHAR(30)   NOT NULL DEFAULT 'registered',
  version                 INT            NOT NULL DEFAULT 1,
  previous_statement_id   NVARCHAR(36)   NULL
    REFERENCES extracted.document(document_id),
  is_latest_version       BIT            NOT NULL DEFAULT 1,
  upload_timestamp        DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

-- ============================================================================
-- extracted.extraction_attempt
-- G1 (append-only, FK to exactly one document) / S10 (written before validation).
-- No application-layer UPDATE path; enforced here via trigger (T1.2 test case).
-- ============================================================================
CREATE TABLE extracted.extraction_attempt (
  attempt_id       NVARCHAR(36)   NOT NULL PRIMARY KEY,
  document_id      NVARCHAR(36)   NOT NULL REFERENCES extracted.document(document_id),
  attempt_no       INT            NOT NULL,
  raw_output       NVARCHAR(MAX)  NULL,
  confidence       FLOAT          NULL,
  provider_used    NVARCHAR(30)   NULL
    CHECK (provider_used IN ('python_library_pdfplumber', 'claude_sonnet', 'pdfplumber_fallback')
           OR provider_used IS NULL),
  arithmetic_pass  BIT            NULL,
  structural_pass  BIT            NULL,
  created_at       DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

CREATE TRIGGER extracted.trg_extraction_attempt_no_update
ON extracted.extraction_attempt
AFTER UPDATE
AS
BEGIN
  RAISERROR('extracted.extraction_attempt is append-only; UPDATE is not permitted.', 16, 1);
  ROLLBACK TRANSACTION;
END;
GO

-- ============================================================================
-- extracted.stmt_vendor_template — NOT a real vendor table. Documents the shape
-- every extracted.stmt_<vendor_slug> table follows; concrete per-vendor tables are
-- created at runtime by src/lib/vendorSchema.ts's generator once a real vendor is
-- registered (Task 3.1), not by this migration — no vendors are known/seeded yet
-- (data baseline = Migrated only, no Seeded component, per UI_SURFACE.md sign-off).
-- G1/S10 (append-only, written before validation) apply to every such table.
-- ============================================================================
-- CREATE TABLE extracted.stmt_<vendor_slug> (
--   row_id       NVARCHAR(36)   NOT NULL PRIMARY KEY,
--   document_id  NVARCHAR(36)   NOT NULL REFERENCES extracted.document(document_id),
--   raw_row      NVARCHAR(MAX)  NOT NULL,   -- native-shape row, preserved as JSON
--   created_at   DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME()
-- );
-- CREATE TRIGGER extracted.trg_stmt_<vendor_slug>_no_update
-- ON extracted.stmt_<vendor_slug> AFTER UPDATE AS
-- BEGIN
--   RAISERROR('extracted.stmt_<vendor_slug> is append-only; UPDATE is not permitted.', 16, 1);
--   ROLLBACK TRANSACTION;
-- END;

-- ============================================================================
-- silver.statement_line
-- S11: amount immutable after extraction — no application-layer UPDATE path;
-- enforced here via trigger, same discipline as extracted.extraction_attempt.
-- Coexists with any existing NetSuite-derived Silver tables — not modified here.
-- ============================================================================
CREATE TABLE silver.statement_line (
  line_id                  NVARCHAR(36)   NOT NULL PRIMARY KEY,
  document_id              NVARCHAR(36)   NOT NULL REFERENCES extracted.document(document_id),
  vendor_id                NVARCHAR(36)   NOT NULL REFERENCES extracted.vendor_registry(vendor_id),
  amount                   DECIMAL(18,2)  NOT NULL,
  invoice_ref              NVARCHAR(100)  NULL,
  normalized_invoice_ref   NVARCHAR(100)  NULL,
  created_at               DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

CREATE TRIGGER silver.trg_statement_line_no_amount_update
ON silver.statement_line
AFTER UPDATE
AS
BEGIN
  IF UPDATE(amount)
  BEGIN
    RAISERROR('silver.statement_line.amount is immutable after extraction (S11).', 16, 1);
    ROLLBACK TRANSACTION;
  END
END;
GO

-- ============================================================================
-- recon.exception
-- S5: category is a fixed, approved enum (DB-enforced via CHECK).
-- owner / aging_started_at / run_reference: nullable, reserved for BCE (D-G/OD3).
--
-- NOTE — enum is a minimal placeholder, not a final list: only the two category
-- values explicitly named anywhere in docs/ARCHITECTURE.md / docs/EXECUTION_PLAN.md
-- / docs/UI_SURFACE.md as of this migration ('not_posted' from Task 5.2's example,
-- 'amount_mismatch' from UI_SURFACE.md's Exception Detail drill-down spec).
-- Task 5.4 ("Wire all exception-creation code paths... using the fixed category
-- enum") owns finalizing the real set — adding values later requires a new
-- migration (ALTER TABLE ... DROP/ADD CONSTRAINT), since this is a CHECK
-- constraint, not an application-layer list. Flagged, not silently assumed final.
-- ============================================================================
CREATE TABLE recon.exception (
  exception_id       NVARCHAR(36)   NOT NULL PRIMARY KEY,
  statement_line_id  NVARCHAR(36)   NOT NULL REFERENCES silver.statement_line(line_id),
  category           NVARCHAR(30)   NOT NULL
    CHECK (category IN ('amount_mismatch', 'not_posted')),
  owner              NVARCHAR(100)  NULL,
  aging_started_at   DATETIME2      NULL,
  run_reference       NVARCHAR(36)   NULL,
  created_at          DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

-- ============================================================================
-- recon.match
-- S8: every match references exactly one immutable snapshot version.
-- ============================================================================
CREATE TABLE recon.match (
  match_id            NVARCHAR(36)   NOT NULL PRIMARY KEY,
  statement_line_id   NVARCHAR(36)   NOT NULL REFERENCES silver.statement_line(line_id),
  snapshot_version    NVARCHAR(50)   NOT NULL,
  created_at           DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME()
);
GO
