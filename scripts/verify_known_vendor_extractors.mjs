// Task 9.8 (EXECUTION_PLAN.md Session 9) — a committed, re-runnable regression check for
// every vendor in knownVendorExtractors.ts. Every one of Session 9's own "reconciles
// exactly" claims (9.1–9.5) was a throwaway scratch script, run once and deleted — not
// independently re-runnable, and not protective against a future edit drifting a vendor's
// extractor out of reconciliation.
//
// Runs through the REAL end-to-end entry points (registerDocument -> triggerExtraction,
// same as e2e_extraction_service_round_trip.mjs), not a vendor's extractor function called
// directly — deliberately, not an oversight: the ensureVendorStmtTable bug found after the
// original Session 9 commits lived one layer ABOVE the extractor (extractionPipeline.ts's
// raw-row write), and every one of that session's own verification passes had called
// identifyAndExtract() in isolation, which is exactly why it shipped unnoticed. A check
// that only re-invokes each extractor function directly would not catch that bug class
// recurring; going through triggerExtraction() does.
//
// Isolated from the shared local dev db (.data/recon.local.db) and uploads folder — this
// runs against its own temp SQLite file + temp uploads dir, cleaned up on exit, so running
// it never pollutes the persistent db the app's own Home/Exceptions screens read from.
//
// Real vendor sample PDFs are NOT committed to this repo (customer statements — privacy,
// size). This script reads them from a documented local path instead; on a machine
// without that folder, each vendor is reported as SKIPPED, not a hard failure — this is a
// local verification aid, not a CI gate that assumes every dev machine has the samples.
//
// Run: npm run test:known-vendor-extractors

import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const tmpDbPath = path.join(__dirname, '..', '.data', 'verify_known_vendors.tmp.db');
const tmpUploadsDir = path.join(__dirname, '..', '.data', 'verify_known_vendors_uploads.tmp');

delete process.env.FABRIC_SQL_ENDPOINT; // force the local sqlite path regardless of .env
process.env.SQLITE_DB_PATH = path.relative(process.cwd(), tmpDbPath);
process.env.UPLOADS_DIR = path.relative(process.cwd(), tmpUploadsDir);

const { runMigrations } = await import('../src/lib/migrate.ts');
const { getSqliteDb, closeDb } = await import('../src/lib/db.ts');
const { registerDocument } = await import('../src/lib/documents.ts');
const { triggerExtraction } = await import('../src/lib/extraction.ts');
const { KNOWN_VENDOR_EXTRACTORS } = await import('../src/lib/knownVendorExtractors.ts');

// Documented path (2026-09-01 investigation) — real vendor statement samples, one file per
// known vendor, keyed by the exact vendor_slug each extractor module exports.
const SAMPLES_DIR = 'C:/Users/yellu/Downloads/Statements';
const SAMPLE_FILES = {
  lia_auto_group: "Lia Vestal.pdf",
  keystone_automotive_industries: "Keystone Neet's.pdf",
  fred_beans_parts: "Fred Beans Lee's.pdf",
  wilberts_inc: "Wilbert's Owego.PDF",
  quirk_auto_group: "Quirk Colemans.PDF",
  adas_calibration_experts: "Adas Calibration Don Joe.pdf",
  empire_auto_parts: "Empire Hewitt's.PDF",
  astech_repairify: "Astech Owego.pdf",
  precision_diagnostics: "Precision Diagnostics Klapec.pdf",
};

let failures = 0;
let skipped = 0;
let checked = 0;

function check(label, condition) {
  if (condition) {
    console.log(`  PASS: ${label}`);
  } else {
    console.error(`  FAIL: ${label}`);
    failures++;
  }
}

runMigrations();
const db = getSqliteDb();

for (const vendor of KNOWN_VENDOR_EXTRACTORS) {
  console.log(`\n== ${vendor.vendorSlug} ==`);
  const filename = SAMPLE_FILES[vendor.vendorSlug];
  const samplePath = filename ? path.join(SAMPLES_DIR, filename) : null;

  if (!samplePath || !fs.existsSync(samplePath)) {
    console.warn(
      `  SKIP: sample not found${filename ? ` at ${samplePath}` : ' (no file mapped in this script)'} — real vendor PDFs aren't committed; only available on a machine with the local sample folder.`
    );
    skipped++;
    continue;
  }

  checked++;
  const bytes = fs.readFileSync(samplePath);
  const { document, duplicate } = registerDocument(bytes, 'verify-known-vendors-entity', filename);
  check('registers as new, not a duplicate', duplicate === false);

  const result = await triggerExtraction(document.documentId);
  check('extraction trigger succeeds', result.ok === true);

  const attempt = db
    .prepare('SELECT * FROM extracted_extraction_attempt WHERE document_id = ? ORDER BY attempt_no DESC LIMIT 1')
    .get(document.documentId);
  check('routed to the deterministic extractor, not Claude/OCR fallback', attempt?.provider_used === 'python_library_pdfplumber');
  check('passed structural + arithmetic validation (reconciles within $0.01)', attempt?.arithmetic_pass === 1 && attempt?.structural_pass === 1);

  const silverRows = db.prepare('SELECT COUNT(*) AS n FROM silver_statement_line WHERE document_id = ?').get(document.documentId);
  check(
    'extracted lines actually reached Silver (regression guard for the ensureVendorStmtTable bug class)',
    silverRows.n > 0
  );
}

await closeDb();

for (const suffix of ['', '-wal', '-shm']) {
  fs.rmSync(tmpDbPath + suffix, { force: true });
}
fs.rmSync(tmpUploadsDir, { recursive: true, force: true });

console.log(`\n${checked} vendor(s) checked, ${skipped} skipped (sample not available on this machine).`);
if (failures > 0) {
  console.error(`${failures} check(s) FAILED.`);
  process.exit(1);
}
if (checked === 0) {
  console.warn('No vendors were actually checked — every sample was unavailable on this machine.');
}
console.log('Known-vendor deterministic extractors: PASS.');
