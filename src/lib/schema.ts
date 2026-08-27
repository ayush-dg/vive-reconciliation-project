import type { DbMode } from './db';

/**
 * Table-name resolution across the two dialect renderings of the same schema
 * (see migrations/001_foundation_schema.sql vs .sqlite.sql for why they differ):
 * Fabric T-SQL uses schema-qualified names (extracted.document); local SQLite
 * uses flattened, schema-prefixed names (extracted_document) so foreign keys
 * stay same-database and are actually enforced.
 */
export function qualifiedTableName(schema: string, table: string, mode: DbMode): string {
  return mode === 'fabric' ? `${schema}.${table}` : `${schema}_${table}`;
}

// Vendor slugs can originate from Claude's document-content-based vendor
// identification for unknown vendors (ARCHITECTURE.md D-L), not only from a
// hand-curated list — so this is a real trust boundary, not a formality.
// Enforced before the slug is ever interpolated into DDL text (schema.ts,
// vendorSchema.ts) since neither SQLite's db.exec() nor mssql's batch() offer
// parameterized identifiers for CREATE TABLE/TRIGGER statements.
const VENDOR_SLUG_PATTERN = /^[a-z][a-z0-9_]{0,62}$/;

export function assertValidVendorSlug(vendorSlug: string): void {
  if (!VENDOR_SLUG_PATTERN.test(vendorSlug)) {
    throw new Error(
      `Invalid vendor slug "${vendorSlug}" — must match ${VENDOR_SLUG_PATTERN} ` +
        '(lowercase letters, digits, underscores; must start with a letter; max 63 chars).'
    );
  }
}

export function vendorStmtTableBaseName(vendorSlug: string): string {
  assertValidVendorSlug(vendorSlug);
  return `stmt_${vendorSlug}`;
}

export function vendorStmtTableName(vendorSlug: string, mode: DbMode): string {
  return qualifiedTableName('extracted', vendorStmtTableBaseName(vendorSlug), mode);
}
