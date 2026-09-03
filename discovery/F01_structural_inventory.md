STAGE-F1-DRAFT: STRUCTURAL — 2026-09-02

# F01_structural_inventory.md — VIVE Statement Reconciliation

Sources read: all 18 migration files (`migrations/001_foundation_schema.sql` through
`009_silver_line_dedup_flag.sql`, plus their `.sqlite.sql` counterparts) in full;
`src/lib/vendorSchema.ts` (runtime per-vendor table generator); `src/lib/schema.ts`
(table-name resolution helpers); `src/lib/fabricLakehouse.ts` (live external Lakehouse
reads); `scripts/netsuiteVendorBillFixture.mjs`, `scripts/cccRepairOrderFixture.mjs`
(external-table test stand-ins). No ORM model definitions exist in this codebase (raw SQL
via `better-sqlite3`/`tedious`/`mssql`, confirmed in prior Stage 2 sessions) — that source
type is absent and was skipped. No ERD/data dictionary exists in this repo — skipped.

## Entity Inventory

| Entity/Table Name | Columns | Types | Notes |
|---|---|---|---|
| `extracted.vendor_registry` | vendor_id (PK), vendor_slug, table_name, extraction_route, created_at | NVARCHAR(36)/TEXT; NVARCHAR(100)/TEXT; NVARCHAR(128)/TEXT; NVARCHAR(20)/TEXT nullable; DATETIME2/TEXT | Created `migrations/001_foundation_schema.sql:29-36` (Fabric) / `.sqlite.sql:28-35`. Maps a vendor to its `stmt_<vendor_slug>` raw table + extraction route. |
| `extracted.document` | document_id (PK), content_sha256, legal_entity_id, artifact_type, vendor_id, statement_period, status, version, previous_statement_id, is_latest_version, upload_timestamp, original_filename | NVARCHAR(36)/TEXT; NVARCHAR(64)/TEXT UNIQUE; NVARCHAR(36)/TEXT; NVARCHAR(50)/TEXT DEFAULT 'vendor_statement'; NVARCHAR(36)/TEXT nullable; NVARCHAR(20)/TEXT nullable; NVARCHAR(30)/TEXT DEFAULT 'registered'; INT/INTEGER DEFAULT 1; NVARCHAR(36)/TEXT nullable (self-FK); BIT/INTEGER DEFAULT 1; DATETIME2/TEXT; NVARCHAR(500)/TEXT nullable (added migration 007) | Created `001_foundation_schema.sql:46-60`; `original_filename` added `007_document_original_filename.sql:7-8`. `version` column exists but is NOT read or written anywhere in `src/` (grepped `documents.ts`, `vendorIdentification.ts`, all of `src/`) — declared, never used by app code. |
| `extracted.extraction_attempt` | attempt_id (PK), document_id (FK), attempt_no, raw_output, confidence, provider_used, arithmetic_pass, structural_pass, created_at | NVARCHAR(36)/TEXT; NVARCHAR(36)/TEXT; INT/INTEGER; NVARCHAR(MAX)/TEXT nullable; FLOAT/REAL nullable; NVARCHAR(30)/TEXT nullable; BIT/INTEGER nullable; BIT/INTEGER nullable; DATETIME2/TEXT | `001_foundation_schema.sql:68-80`. Append-only: no application-layer UPDATE path, enforced via `extracted.trg_extraction_attempt_no_update` (Fabric, AFTER UPDATE, `:83-91`) / `trg_extraction_attempt_no_update` (SQLite, BEFORE UPDATE, `.sqlite.sql:67-71`). |
| `extracted.stmt_<vendor_slug>` (dynamic per-vendor table pattern, not a fixed name) | row_id (PK), document_id (FK), raw_row, created_at | NVARCHAR(36)/TEXT; NVARCHAR(36)/TEXT; NVARCHAR(MAX)/TEXT NOT NULL; DATETIME2/TEXT | NOT created by any migration file — `001_foundation_schema.sql:93-112` only documents the shape as a commented-out template (no vendors known/seeded at migration time). Concrete tables are created at runtime by `src/lib/vendorSchema.ts`'s `ensureVendorStmtTable()` (`vendorSchema.ts:15-65`), one per registered vendor, name = `extracted.stmt_<vendor_slug>` (Fabric) / `extracted_stmt_<vendor_slug>` (SQLite), via `src/lib/schema.ts:31-38`'s `vendorStmtTableName()`. Confirmed by direct comparison: the runtime-generated DDL (`vendorSchema.ts:18-34`, `:36-52`) is column-for-column identical to the migration's commented template — no drift found. Same append-only-via-trigger discipline as `extraction_attempt`. |
| `silver.statement_line` | line_id (PK), document_id (FK), vendor_id (FK), amount, invoice_ref, normalized_invoice_ref, created_at, normalization_version, is_duplicate_line | NVARCHAR(36)/TEXT; NVARCHAR(36)/TEXT; NVARCHAR(36)/TEXT; DECIMAL(18,2)/NUMERIC NOT NULL; NVARCHAR(100)/TEXT nullable; NVARCHAR(100)/TEXT nullable; DATETIME2/TEXT; NVARCHAR(20)/TEXT DEFAULT 'v1' (added migration 003); BIT/INTEGER DEFAULT 0 (added migration 009) | `001_foundation_schema.sql:120-128`; `normalization_version` added `003_normalization_version.sql:8-9`; `is_duplicate_line` added `009_silver_line_dedup_flag.sql:9-10`. `amount` immutable after write — no application-layer UPDATE path, enforced via `silver.trg_statement_line_no_amount_update` (Fabric AFTER UPDATE, `:131-141`) / `trg_statement_line_no_amount_update` (SQLite BEFORE UPDATE OF amount, `.sqlite.sql:87-91`). The one shared, vendor-agnostic table per Stage 1's INTAKE_SUMMARY.md. |
| `recon.exception` | exception_id (PK), statement_line_id (FK), category, owner, aging_started_at, run_reference, created_at, reference_run_id, reference_extracted_at, reference_source_system, evidence, reason_codes, status, note, resolved_at | NVARCHAR(36)/TEXT; NVARCHAR(36)/TEXT; NVARCHAR(30)/TEXT NOT NULL CHECK; NVARCHAR(100)/TEXT nullable; DATETIME2/TEXT nullable; NVARCHAR(36)/TEXT nullable; DATETIME2/TEXT; NVARCHAR(100)/TEXT nullable (005); DATETIME2/TEXT nullable (005); NVARCHAR(50)/TEXT nullable (005); NVARCHAR(MAX)/TEXT nullable (005); NVARCHAR(MAX)/TEXT NOT NULL DEFAULT '[]' (006); NVARCHAR(20)/TEXT NOT NULL DEFAULT 'open' CHECK (008); NVARCHAR(MAX)/TEXT nullable (008); DATETIME2/TEXT nullable (008) | Base: `001_foundation_schema.sql:158-168`. reference_* + evidence added `005_reference_capture_schema.sql:24-29`. reason_codes added `006_exception_reason_codes.sql:10-11`. status/note/resolved_at added `008_exception_status.sql:8-13` (Fabric uses named constraints `DF_exception_status`/`CK_exception_status`). owner/aging_started_at/run_reference are reserved for BCE and never populated by this build (confirmed by `src/lib/exceptionWriter.ts:14` comment and `scripts/test_exception_schema_wiring.mjs` TC-3). |
| `recon.match` | match_id (PK), statement_line_id (FK), created_at, reference_run_id, reference_extracted_at, reference_source_system | NVARCHAR(36)/TEXT; NVARCHAR(36)/TEXT; DATETIME2/TEXT; NVARCHAR(100)/TEXT NOT NULL (005); DATETIME2/TEXT NOT NULL (005); NVARCHAR(50)/TEXT NOT NULL (005) | Base (`001_foundation_schema.sql:174-180`) originally had a `snapshot_version NVARCHAR(50) NOT NULL` column instead — DROPPED and replaced by the three `reference_*` NOT NULL columns in `005_reference_capture_schema.sql:8-15` (Fabric: `ALTER ... DROP COLUMN` then `ADD`; SQLite: `DROP TABLE`/`CREATE TABLE`, `.sqlite.sql:9-18`, since no session before 005 had written rows). Column order differs slightly between dialects post-005 (Fabric appends the 3 new columns after `created_at`; SQLite's recreated table places them before `created_at`) — cosmetic only, no app code depends on column order (all reads/writes use named columns). |
| `recon.app_user` | user_id (PK), username, password_hash, display_name, created_at | NVARCHAR(36)/TEXT; NVARCHAR(100)/TEXT UNIQUE; NVARCHAR(200)/TEXT; NVARCHAR(200)/TEXT nullable; DATETIME2/TEXT | `002_auth_users.sql:12-18`. Not part of Task 1.2's original schema list — flagged in the migration's own header comment as filling an undocumented plan gap (Sign In needs a persisted user store). `password_hash` format is `"<hex salt>:<hex scrypt hash>"` (`src/lib/auth.ts:12-16`), not a bare hash. |
| `recon.document_lock` | document_id (PK, FK to extracted.document), acquired_at | NVARCHAR(36)/TEXT; DATETIME2/TEXT | `004_matching_lock.sql:10-15`. G5's per-invocation matching-ownership lock (distinct dimension from `extracted.document.status`'s one-way extraction lock). Staleness window = 10 minutes, `src/lib/matchingInvocation.ts:39` (`LOCK_STALE_AFTER_MINUTES`). |
| `bronze.netsuite_vendorbill` — **external, not owned by this build's migrations**, columns as observed only | tranid, total, entity, _run_id, _extracted_at, _source_system (+ arbitrary other live columns) | Not independently typed here (external) | Live-observed columns per `src/lib/fabricLakehouse.ts:31,106-118,148` (`tranid`, `total`, `entity` used to JOIN `bronze.netsuite_vendor`, `_run_id`, `_extracted_at`, `_source_system`, plus every other column captured verbatim into `rawFields`). Engineer-confirmed by direct Lakehouse inspection per `src/lib/deterministicMatching.ts:12-16`. See F02 Naming Pattern Flags — the SQLite test fixture (`scripts/netsuiteVendorBillFixture.mjs`) uses a DIFFERENT, non-matching column-naming scheme for what is nominally the same table. |
| `bronze.netsuite_vendorcredit` — **external, not owned by this build's migrations**, columns as observed only | Same shape as `bronze.netsuite_vendorbill` (per `fabricLakehouse.ts:198-203` comment) | Not independently typed here (external) | Referenced only in `src/lib/fabricLakehouse.ts:198,204-210` (`CREDIT_TABLE`) and `src/lib/deterministicMatching.ts:94-96`. "Same shape, confirmed 2026-08-31" per source comment — not independently re-verified in any file read for this session. |
| `bronze.netsuite_vendor` — **external, not owned by this build's migrations**, columns as observed only | id, entityid | Not independently typed here (external) | Referenced only as a JOIN target in `src/lib/fabricLakehouse.ts:148` (`JOIN bronze.netsuite_vendor v ON v.id = b.entity ... LOWER(v.entityid) LIKE ...`). Not named in the task brief's external-table list but genuinely read by this build's own code — included per "record everything." |
| `bronze.ccc_repair_order` (or equivalent, real name **unconfirmed**) — **external, not owned by this build's migrations**, columns as observed only | ro_number, vendor_name, amount, _run_id, _extracted_at, _source_system | Not independently typed here (external) | `bronze_ccc_repair_order` is this project's own placeholder name (per `scripts/cccRepairOrderFixture.mjs:2-8` and `src/lib/aiResidualMatching.ts:17-22` comments) — CCC's real production table name is NOT engineer-confirmed anywhere in source (unlike `bronze.netsuite_vendorbill`). Query failure against this name degrades gracefully to "no corroboration available" (`aiResidualMatching.ts:53-61`), it does not throw. |

## Relationship Inventory

| Relationship | Declaration Type | Source Entity | Target Entity | Notes |
|---|---|---|---|---|
| document.vendor_id -> vendor_registry.vendor_id | FK | `extracted.document` | `extracted.vendor_registry` | `001_foundation_schema.sql:51-52`. Nullable — not known at registration (populated during extraction, `vendorIdentification.ts:234-239`). |
| document.previous_statement_id -> document.document_id | FK (self-referencing) | `extracted.document` | `extracted.document` | `001_foundation_schema.sql:56-57`. Version-chaining link, set by `vendorIdentification.ts:135-156`'s `runVersionChaining()`. |
| extraction_attempt.document_id -> document.document_id | FK | `extracted.extraction_attempt` | `extracted.document` | `001_foundation_schema.sql:70`. |
| stmt_<vendor_slug>.document_id -> document.document_id | FK | `extracted.stmt_<vendor_slug>` (dynamic, per-vendor) | `extracted.document` | `vendorSchema.ts:21,42` (runtime DDL); mirrors the commented template's FK at `001_foundation_schema.sql:103`. |
| statement_line.document_id -> document.document_id | FK | `silver.statement_line` | `extracted.document` | `001_foundation_schema.sql:122`. |
| statement_line.vendor_id -> vendor_registry.vendor_id | FK | `silver.statement_line` | `extracted.vendor_registry` | `001_foundation_schema.sql:123`. NOT NULL (unlike document.vendor_id) — a line only reaches Silver once vendor is known. |
| exception.statement_line_id -> statement_line.line_id | FK | `recon.exception` | `silver.statement_line` | `001_foundation_schema.sql:160`. |
| match.statement_line_id -> statement_line.line_id | FK | `recon.match` | `silver.statement_line` | `001_foundation_schema.sql:176`. |
| document_lock.document_id -> document.document_id | FK | `recon.document_lock` | `extracted.document` | `004_matching_lock.sql:11-12`. |
| vendor_registry.table_name -> stmt_<vendor_slug> table | INFERRED | `extracted.vendor_registry` | `extracted.stmt_<vendor_slug>` | Not DB-enforced — a stored string naming a dynamically-created table, resolved only by app code (`vendorSchema.ts`, `extractionPipeline.ts:138`). No FK possible since the target table doesn't exist until runtime. |
| match/exception reference_* columns -> bronze.netsuite_vendorbill/vendorcredit row | INFERRED | `recon.match` / `recon.exception` | `bronze.netsuite_vendorbill` / `bronze.netsuite_vendorcredit` | Not an FK (external system, possibly different database entirely; source is upsert-in-place with no retained history per `deterministicMatching.ts:28-35`) — captured as a point-in-time snapshot (`reference_run_id`/`reference_extracted_at`/`reference_source_system`) at match time instead. |
| exception.evidence (JSON) -> bronze.ccc_repair_order row | INFERRED | `recon.exception` | `bronze.ccc_repair_order` | No FK — `aiResidualMatching.ts:139` embeds `cccCorroboration` (including `ro_number`) into the JSON `evidence` blob, not a relational reference. |
| deterministicMatching query -> bronze.netsuite_vendor | JOIN_TABLE | (query-time only, `fabricLakehouse.ts:148`) | `bronze.netsuite_vendor` | Live Fabric-only SQL JOIN (`b.entity = v.id`), not present in the local SQLite fixture path at all (no vendor-scoping table exists there) — an asymmetry between the two lookup paths, not a DB-level constraint. |
| aiResidualMatching lookup -> bronze.ccc_repair_order | INFERRED | (query-time only, `aiResidualMatching.ts:35-62`) | `bronze.ccc_repair_order` | No join key beyond amount-tolerance proximity (`ABS(amount - ?) <= 0.01`) — no vendor/date narrowing exists (per source's own "narrowly-scoped" framing). |

## Constraint Inventory

| Entity | Constraint Type | Fields | Notes |
|---|---|---|---|
| `extracted.vendor_registry` | UNIQUE | vendor_slug | `001_foundation_schema.sql:31`. |
| `extracted.vendor_registry` | CHECK | extraction_route | `IN ('deterministic','claude_primary') OR NULL` — `:34`. Note: `'claude_primary'` is declared but never written anywhere in `src/` (see F02). |
| `extracted.vendor_registry` | NOT_NULL | vendor_id, vendor_slug, table_name, created_at | `:30-35`. |
| `extracted.document` | UNIQUE | content_sha256 | `:48`. Content-hash idempotency (G4). |
| `extracted.document` | NOT_NULL | document_id, content_sha256, legal_entity_id, artifact_type, status, version, is_latest_version, upload_timestamp | `:47-59`. |
| `extracted.extraction_attempt` | CHECK | provider_used | `IN ('python_library_pdfplumber','claude_sonnet','pdfplumber_fallback') OR NULL` — `:75-76`. |
| `extracted.extraction_attempt` | NOT_NULL | attempt_id, document_id, attempt_no, created_at | `:69-79`. |
| `extracted.extraction_attempt` | (append-only, enforced via trigger, not a CHECK) | (all columns) | `trg_extraction_attempt_no_update` — `:83-91` (Fabric) / `.sqlite.sql:67-71` (SQLite). Not one of the 4 listed constraint types; recorded here for completeness. |
| `extracted.stmt_<vendor_slug>` | NOT_NULL | row_id, document_id, raw_row, created_at | `vendorSchema.ts:20-23`. |
| `extracted.stmt_<vendor_slug>` | (append-only, enforced via trigger) | (all columns) | `trg_stmt_<vendor_slug>_no_update` per instance — `vendorSchema.ts:25-32,46-49`. |
| `silver.statement_line` | NOT_NULL | line_id, document_id, vendor_id, amount, created_at, normalization_version, is_duplicate_line | `001_foundation_schema.sql:121-127`; `003:9`; `009:10`. |
| `silver.statement_line` | (amount immutable, enforced via trigger, not a CHECK) | amount | `trg_statement_line_no_amount_update` — `:131-141` (Fabric) / `.sqlite.sql:87-91` (SQLite). S11. |
| `recon.exception` | CHECK | category | `IN ('amount_mismatch','not_posted')` — `001_foundation_schema.sql:162`. Flagged in the migration's own comment (`:149-156`) as "a minimal placeholder, not a final list." |
| `recon.exception` | CHECK | status | `IN ('open','resolved','flagged','skipped')` — `008_exception_status.sql:10` (Fabric: named `CK_exception_status`) / `.sqlite.sql:9` (SQLite: inline). |
| `recon.exception` | NOT_NULL | exception_id, statement_line_id, category, created_at, reason_codes, status | `001_foundation_schema.sql:159-166`; `006:11`; `008:9`. |
| `recon.match` | NOT_NULL | match_id, statement_line_id, created_at, reference_run_id, reference_extracted_at, reference_source_system | `001_foundation_schema.sql:175-178`; `005_reference_capture_schema.sql:12-14`. |
| `recon.app_user` | UNIQUE | username | `002_auth_users.sql:14`. |
| `recon.app_user` | NOT_NULL | user_id, username, password_hash, created_at | `:12-18`. |
| `recon.document_lock` | NOT_NULL | document_id, acquired_at | `004_matching_lock.sql:11-13`. |
| (all tables) | INDEX | — | No explicit `CREATE INDEX` statement exists in any of the 18 migration files — every index this schema has is implicit, via PRIMARY KEY or UNIQUE constraints only. Flagged as NOT DETERMINABLE beyond that (no separate index-tuning pass found). |

## Divergence Flags

*(none raised)*

Every Fabric/.sqlite.sql migration pair was read in full and compared column-by-column,
type-by-type, and constraint-by-constraint. All differences found are the already-documented,
expected dialect fork (schema-qualified `extracted.document` vs. flattened `extracted_document`
naming; `NVARCHAR`/`DATETIME2`/`BIT`/`DECIMAL` vs. `TEXT`/`REAL`/`INTEGER`/`NUMERIC` type
mapping; `AFTER UPDATE`+`RAISERROR`/`ROLLBACK` vs. `BEFORE UPDATE`+`RAISE(ABORT)` trigger
mechanics; named constraints in Fabric — e.g. `DF_exception_status`, `CK_exception_status`,
`DF_statement_line_is_duplicate` — vs. anonymous inline constraints in SQLite; and migration
005's `ALTER...DROP/ADD` vs. `DROP TABLE`/`CREATE TABLE` rendering of the same net column
change on `recon.match`, which both dialects document explicitly as deliberate). No case was
found where one dialect has a column, constraint, or table the other lacks.

The one non-cosmetic structural change found (`recon.match.snapshot_version` dropped and
replaced with `reference_run_id`/`reference_extracted_at`/`reference_source_system` NOT NULL,
migration 005) is applied identically in both dialects — not a cross-dialect divergence, but
recorded in the Entity Inventory above since it's a genuine schema evolution worth noting.
