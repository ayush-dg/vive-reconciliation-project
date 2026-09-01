import crypto from 'node:crypto';
import { getSqliteDb, getDbMode } from './db';
import { assertValidVendorSlug } from './schema';
import { extractViaClaude } from './aiProvider';
import { extractViaPdfplumber } from './pdfplumberExtractor';
import { extractViaPdfplumberOcrFallback } from './pdfplumberOcrFallback';
import { findKnownVendorExtractor } from './knownVendorExtractors';
import type { ExtractionOutcome } from './aiProvider';

/**
 * Vendor identification, extraction routing, and version-chaining (Task 3.1,
 * amended 2026-08-27). Checks extracted.vendor_registry for a known-vendor
 * match; no match routes to the Claude-primary path with provisional vendor
 * creation. Once vendor/period are known, runs the version-chaining check
 * moved here from Task 2.2 (S2).
 *
 * "Signature/layout match" (ARCHITECTURE.md's phrase for the known-vendor
 * check) has no real per-vendor layout fingerprint to match against yet — no
 * vendor has been onboarded (data baseline = Migrated only, no seed data).
 * This build uses the same vendor-name signal aiProvider.ts's mock/pdfplumber
 * extractors already read (a "VENDOR: <name>" marker in the test fixtures) as
 * a stand-in signature: if a registry entry's vendor_slug matches the
 * slugified guess, that's the "known-vendor" match. Flagged as a real
 * simplification, not a production per-vendor fingerprinting system.
 */

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('vendorIdentification.ts only supports the local SQLite fallback — Fabric required starting Session 4.');
  }
}

// Known, accepted limitation: two distinct vendor names that differ only in
// punctuation/case (e.g. "A&B Co" vs. "A B Co") normalize to the same slug
// and are therefore treated as the same vendor. Real per-vendor layout
// fingerprinting (ARCHITECTURE.md's actual "signature/layout match") would
// avoid this, but no real vendor has been onboarded yet to build one against
// (data baseline = Migrated only, no seed data) — accepted for this bounded
// build, not fixed here.
function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/^(?=[0-9])/, 'v_'); // slugs must start with a letter (schema.ts's guard)
}

/** Peeks at the PDF's own text to guess a vendor slug, without committing to
 * a full extraction — used only to decide routing before the real
 * extraction call runs. Falls back to the deterministic (non-AI) text
 * extractor for this peek regardless of which path is ultimately chosen,
 * since it's just a cheap text scan, not the routed extraction itself. */
async function peekVendorSlug(pdfBytes: Buffer): Promise<{ slug: string | null; pdfText: string }> {
  const peek = await extractViaPdfplumber(pdfBytes);
  const name = peek.extracted?.vendorNameGuess ?? null;
  return { slug: name ? slugify(name) : null, pdfText: peek.rawOutput };
}

export type VendorRegistryRow = {
  vendorId: string;
  vendorSlug: string;
  tableName: string;
  extractionRoute: 'deterministic' | 'claude_primary' | null;
};

function findVendorBySlug(vendorSlug: string): VendorRegistryRow | null {
  const db = getSqliteDb();
  const row = db
    .prepare('SELECT vendor_id, vendor_slug, table_name, extraction_route FROM extracted_vendor_registry WHERE vendor_slug = ?')
    .get(vendorSlug) as
    | { vendor_id: string; vendor_slug: string; table_name: string; extraction_route: string | null }
    | undefined;
  if (!row) return null;
  return {
    vendorId: row.vendor_id,
    vendorSlug: row.vendor_slug,
    tableName: row.table_name,
    extractionRoute: row.extraction_route as VendorRegistryRow['extractionRoute'],
  };
}

function createProvisionalVendor(vendorSlug: string): VendorRegistryRow {
  assertValidVendorSlug(vendorSlug); // same trust-boundary guard as vendorSchema.ts
  const db = getSqliteDb();
  const vendorId = crypto.randomUUID();
  const tableName = `extracted_stmt_${vendorSlug}`;
  db.prepare(
    `INSERT INTO extracted_vendor_registry (vendor_id, vendor_slug, table_name, extraction_route)
     VALUES (?, ?, ?, NULL)`
  ).run(vendorId, vendorSlug, tableName);
  return { vendorId, vendorSlug, tableName, extractionRoute: null };
}

/** Task 8.1, generalized in Session 9 (2026-09-01) — each vendor in
 * knownVendorExtractors.ts's table ships a real per-vendor deterministic
 * Python extractor. Unlike createProvisionalVendor (an unknown vendor
 * Claude just identified, extraction_route left NULL pending manual
 * onboarding), these vendors are known in advance — the registry row is
 * created with extraction_route='deterministic' on first sight, no
 * "Migrated only, no seed data" violation since nothing is seeded ahead of
 * an actual document needing it. */
function ensureKnownVendor(vendorSlug: string): VendorRegistryRow {
  const existing = findVendorBySlug(vendorSlug);
  if (existing) return existing;
  const db = getSqliteDb();
  const vendorId = crypto.randomUUID();
  const tableName = `extracted_stmt_${vendorSlug}`;
  db.prepare(
    `INSERT INTO extracted_vendor_registry (vendor_id, vendor_slug, table_name, extraction_route)
     VALUES (?, ?, ?, 'deterministic')`
  ).run(vendorId, vendorSlug, tableName);
  return { vendorId, vendorSlug, tableName, extractionRoute: 'deterministic' };
}

/** S2 — a non-identical document for an already-processed vendor/period/
 * entity combination is version-chained to the prior document, not left
 * disconnected. No human-reviewed flag (D-H amended). Moved here from Task
 * 2.2, which no longer has vendor/period available at registration time. */
function runVersionChaining(documentId: string, vendorId: string, statementPeriod: string | null, legalEntityId: string): void {
  if (!statementPeriod) return; // nothing to chain against without a period
  const db = getSqliteDb();
  const prior = db
    .prepare(
      `SELECT document_id FROM extracted_document
       WHERE vendor_id = ? AND statement_period = ? AND legal_entity_id = ?
         AND document_id != ? AND is_latest_version = 1`
    )
    .get(vendorId, statementPeriod, legalEntityId, documentId) as { document_id: string } | undefined;

  if (!prior) return;

  const chain = db.transaction(() => {
    db.prepare(`UPDATE extracted_document SET is_latest_version = 0 WHERE document_id = ?`).run(prior.document_id);
    db.prepare(`UPDATE extracted_document SET previous_statement_id = ?, is_latest_version = 1 WHERE document_id = ?`).run(
      prior.document_id,
      documentId
    );
  });
  chain();
}

export type IdentifyAndExtractResult = {
  // Null when no vendor name could be identified at all (e.g. a structurally
  // broken PDF with no readable vendor signal) — NOT thrown as an error,
  // since G1/S10 require an extraction_attempt to be written regardless of
  // outcome; the pipeline orchestrator writes the attempt with vendor_id
  // left NULL, and Task 3.2's validation gate fails it on structural grounds.
  vendor: VendorRegistryRow | null;
  provider: 'python_library_pdfplumber' | 'claude_sonnet' | 'pdfplumber_fallback';
  outcome: ExtractionOutcome;
};

/** Orchestrates: vendor identification -> routing -> extraction call (NOT
 * yet writing extraction_attempt — that's the pipeline orchestrator's job,
 * per S10's write-before-validation ordering, which needs the outcome first
 * to write it). Populates document.vendor_id/statement_period and runs
 * version-chaining once the vendor is known. */
// No match found via the pre-extraction peek — Claude-primary path,
// provisional vendor creation. A genuinely new vendor is not an error
// (ARCHITECTURE.md D-L). Extracted to keep identifyAndExtract's own nesting
// at or below CQ-001's two-level cap.
function resolveProvisionalVendor(outcome: ExtractionOutcome, guessedSlug: string | null): VendorRegistryRow | null {
  const resolvedSlug = outcome.extracted?.vendorNameGuess ? slugify(outcome.extracted.vendorNameGuess) : guessedSlug;
  if (!resolvedSlug) return null;
  return findVendorBySlug(resolvedSlug) ?? createProvisionalVendor(resolvedSlug);
}

/** forceFallback (Task 8.2/8.3, 2026-09-01): set by extractionPipeline.ts's
 * retry loop when attempt 1 was a genuine Claude failure (extracted === null
 * for a document that would otherwise have routed to Claude) — routes
 * straight to the OCR/pdfplumber fallback tier instead of an identical
 * Claude retry. Never set for a document with a known deterministic
 * vendor — that path doesn't call Claude in the first place, so this
 * routing question never arises for it. */
export async function identifyAndExtract(
  documentId: string,
  legalEntityId: string,
  pdfBytes: Buffer,
  forceFallback = false
): Promise<IdentifyAndExtractResult> {
  assertSqliteMode();
  const db = getSqliteDb();

  const { slug: guessedSlug, pdfText } = await peekVendorSlug(pdfBytes);
  const matched = guessedSlug ? findVendorBySlug(guessedSlug) : null;

  let vendor = matched;
  let provider: 'python_library_pdfplumber' | 'claude_sonnet' | 'pdfplumber_fallback';
  let outcome: ExtractionOutcome;

  // Task 8.1, generalized in Session 9 — checked BEFORE the generic
  // guessedSlug/matched path: a real known-vendor statement has no
  // synthetic "VENDOR: <name>" marker for peekVendorSlug's regex to find
  // (that marker only exists in this project's own test fixtures), so it
  // would otherwise never match a registry row no matter how the registry
  // itself is configured. This checks the document's real, raw text
  // against each known vendor's own printed signature instead — the one
  // genuine "signature/layout match" this build performs.
  const knownVendor = findKnownVendorExtractor(pdfText);

  if (knownVendor) {
    provider = 'python_library_pdfplumber';
    vendor = ensureKnownVendor(knownVendor.vendorSlug);
    outcome = await knownVendor.extract(pdfBytes);
  } else if (matched && matched.extractionRoute === 'deterministic') {
    provider = 'python_library_pdfplumber';
    outcome = await extractViaPdfplumber(pdfBytes);
  } else if (forceFallback) {
    provider = 'pdfplumber_fallback';
    outcome = await extractViaPdfplumberOcrFallback(pdfBytes);
    vendor = matched ?? resolveProvisionalVendor(outcome, guessedSlug);
  } else {
    provider = 'claude_sonnet';
    outcome = await extractViaClaude(pdfBytes, pdfText);
    vendor = matched ?? resolveProvisionalVendor(outcome, guessedSlug);
  }

  if (vendor) {
    db.prepare(`UPDATE extracted_document SET vendor_id = ?, statement_period = ? WHERE document_id = ?`).run(
      vendor.vendorId,
      outcome.extracted?.statementPeriod ?? null,
      documentId
    );
    runVersionChaining(documentId, vendor.vendorId, outcome.extracted?.statementPeriod ?? null, legalEntityId);
  }
  // vendor === null: document.vendor_id/statement_period stay NULL (same as
  // at registration) — not an error. See IdentifyAndExtractResult's doc comment.

  return { vendor, provider, outcome };
}
