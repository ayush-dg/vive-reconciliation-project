import crypto from 'node:crypto';
import { getSqliteDb, getDbMode } from './db';
import { readDocumentFile } from './storage';
import { identifyAndExtract } from './vendorIdentification';
import type { VendorRegistryRow } from './vendorIdentification';
import { validateExtraction } from './validationGate';
import { normalizeToSilver } from './silverNormalization';
import type { ExtractedStatement } from './aiProvider';

/**
 * Extraction pipeline orchestrator — ties together Tasks 3.1 (vendor
 * identification/routing/attempt recording), 3.2 (validation gate), 3.3
 * (bounded retry), and 3.6 (Silver normalization) into the single flow
 * Task 2.4's Extract trigger invokes (replacing Session 2's stub).
 *
 * S10/G1 — every attempt (success or failure) is written to
 * extracted_extraction_attempt BEFORE this function decides whether to
 * retry; existing attempt rows are never modified (enforced at the schema
 * level, Task 1.2 — this module only ever INSERTs).
 * S7 — at most 2 total attempts; the loop below is the sole enforcement point.
 */

const MAX_ATTEMPTS = 2; // S7

function assertSqliteMode() {
  if (getDbMode() !== 'sqlite') {
    throw new Error('extractionPipeline.ts only supports the local SQLite fallback — Fabric required starting Session 4.');
  }
}

function getExistingAttemptCount(documentId: string): number {
  const db = getSqliteDb();
  const row = db
    .prepare('SELECT COUNT(*) AS n FROM extracted_extraction_attempt WHERE document_id = ?')
    .get(documentId) as { n: number };
  return row.n;
}

// Idempotency guard: nothing else in this codebase stops a direct call to
// runExtractionPipeline (bypassing extraction.ts's G5 lock, e.g. a future
// batch-reprocessing caller) from re-running an already-succeeded document —
// re-entering the loop would write a duplicate attempt row and a duplicate
// silver_statement_line row for the same statement line, with no DB-level
// uniqueness constraint to catch it either.
function hasAlreadySucceeded(documentId: string): boolean {
  const db = getSqliteDb();
  const latest = db
    .prepare(
      `SELECT arithmetic_pass, structural_pass FROM extracted_extraction_attempt
       WHERE document_id = ? ORDER BY attempt_no DESC LIMIT 1`
    )
    .get(documentId) as { arithmetic_pass: number | null; structural_pass: number | null } | undefined;
  return !!latest && latest.arithmetic_pass === 1 && latest.structural_pass === 1;
}

export async function runExtractionPipeline(documentId: string): Promise<void> {
  assertSqliteMode();
  const db = getSqliteDb();

  const document = db
    .prepare('SELECT content_sha256, legal_entity_id FROM extracted_document WHERE document_id = ?')
    .get(documentId) as { content_sha256: string; legal_entity_id: string } | undefined;
  if (!document) {
    throw new Error(`runExtractionPipeline: document ${documentId} not found.`);
  }

  if (hasAlreadySucceeded(documentId)) {
    return; // already promoted to Silver — never reprocess (idempotency guard)
  }

  let attemptNo = getExistingAttemptCount(documentId);
  while (attemptNo < MAX_ATTEMPTS) {
    attemptNo += 1;

    // S10 — a catastrophic failure mid-attempt (subprocess spawn error,
    // missing document file) must still leave an attempt row; these tables
    // must never silently omit a failed attempt. Caught here, not left to
    // propagate past the write below.
    let provider: 'python_library_pdfplumber' | 'claude_sonnet' | null = null;
    let rawOutput = '';
    let confidence: number | null = null;
    let arithmeticPass = false;
    let structuralPass = false;
    let vendor: VendorRegistryRow | null = null;
    let extracted: ExtractedStatement | null = null;

    try {
      const pdfBytes = readDocumentFile(document.content_sha256);
      const result = await identifyAndExtract(documentId, document.legal_entity_id, pdfBytes);
      vendor = result.vendor;
      provider = result.provider;
      rawOutput = result.outcome.rawOutput;
      confidence = result.outcome.confidence;
      extracted = result.outcome.extracted;

      const validation = validateExtraction(extracted);
      // Both flags require extracted !== null — otherwise a total extraction
      // failure (EXTRACTION_ERROR, neither reason code present) would record
      // arithmetic_pass=1 despite arithmetic never having been assessed at
      // all, the same misleading "looks healthy" audit-trail gap Task 3.1's
      // structural_pass fix closed for the missing-vendor case.
      arithmeticPass = extracted !== null && !validation.reasonCodes.includes('ARITHMETIC_MISMATCH');
      structuralPass = extracted !== null && !validation.reasonCodes.includes('MISSING_IDENTIFIER');
    } catch (err) {
      rawOutput = `attempt failed before extraction outcome was available: ${err instanceof Error ? err.message : String(err)}`;
    }

    // S10/G1 — write the attempt BEFORE any retry decision, unconditionally.
    db.prepare(
      `INSERT INTO extracted_extraction_attempt
         (attempt_id, document_id, attempt_no, raw_output, confidence, provider_used, arithmetic_pass, structural_pass)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      crypto.randomUUID(),
      documentId,
      attemptNo,
      rawOutput,
      confidence,
      provider,
      arithmeticPass ? 1 : 0,
      structuralPass ? 1 : 0
    );

    // Known-vendor deterministic path also writes the raw per-vendor row —
    // Claude-path raw output lands only in extraction_attempt.raw_output
    // (Task 3.1's own text: "no stmt_<vendor_slug> row required for that path").
    if (provider === 'python_library_pdfplumber' && vendor) {
      db.prepare(`INSERT INTO ${vendor.tableName} (row_id, document_id, raw_row) VALUES (?, ?, ?)`).run(
        crypto.randomUUID(),
        documentId,
        JSON.stringify(extracted)
      );
    }

    if (arithmeticPass && structuralPass && extracted && vendor) {
      try {
        normalizeToSilver(documentId, vendor.vendorId, extracted);
      } catch (err) {
        // The attempt row above is already committed and correctly reflects
        // that extraction validation passed (G1 forbids rewriting it, and
        // that fact is true) — but an unexpected failure at this downstream
        // step must not vanish as an unhandled rejection with no diagnostic
        // trail. Re-thrown with context rather than silently swallowed.
        throw new Error(
          `runExtractionPipeline: document ${documentId} passed validation on attempt ${attemptNo} but Silver normalization failed: ${err instanceof Error ? err.message : String(err)}`
        );
      }
      return; // success — no further attempts
    }

    if (attemptNo >= MAX_ATTEMPTS) {
      // S7's bound reached. No document.status flip is needed here — Task
      // 2.3's status computation derives "Failed — see Exceptions" purely
      // from attempt history (2 failed attempts), independent of the
      // document.status column Task 2.4's G5 lock already set to 'processing'.
      return;
    }
    // else: loop again for the next attempt (Task 3.3's bounded retry).
  }
}
