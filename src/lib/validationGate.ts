import type { ExtractedStatement } from './aiProvider';

/**
 * Arithmetic + structural validation gate (Task 3.2). Confidence is NOT part
 * of this gate (G2, amended) — it is recorded elsewhere as diagnostic
 * metadata only. Structured result contract per ARCHITECTURE.md D-K: stage,
 * status, reason_codes, evidence, requires_review — not a bare boolean.
 */

export type ValidationResult = {
  stage: 'validation';
  status: 'pass' | 'fail';
  reasonCodes: string[];
  evidence: Record<string, unknown>;
  requiresReview: boolean;
};

const ARITHMETIC_TOLERANCE = 0.01; // 1 cent, per "within a defined tolerance"

function isParseableDate(value: string): boolean {
  return !Number.isNaN(Date.parse(value));
}

export function validateExtraction(extracted: ExtractedStatement | null): ValidationResult {
  if (!extracted) {
    return {
      stage: 'validation',
      status: 'fail',
      reasonCodes: ['EXTRACTION_ERROR'],
      evidence: {},
      requiresReview: true,
    };
  }

  const reasonCodes: string[] = [];
  const evidence: Record<string, unknown> = {};

  // --- Structural: invoice_ref or ro_number fallback required on every line;
  // amounts (when present) must be numeric; dates (when present) must parse.
  // A blank amount alone (credit/payment line) is NOT a structural failure.
  const structuralIssues: { lineIndex: number; issue: string }[] = [];
  extracted.lines.forEach((line, lineIndex) => {
    if (!line.invoiceRef && !line.roNumber) {
      structuralIssues.push({ lineIndex, issue: 'missing invoice_ref/ro_number' });
    }
    if (line.amount !== null && Number.isNaN(line.amount)) {
      structuralIssues.push({ lineIndex, issue: 'amount is not numeric' });
    }
    if (line.date !== null && !isParseableDate(line.date)) {
      structuralIssues.push({ lineIndex, issue: 'date does not parse' });
    }
  });
  // An unidentifiable vendor is a structural failure too (G2/IC-2's "required
  // fields present" test), not a silent extra gate outside this contract —
  // without it, a document with valid line items but no vendor name would
  // record arithmetic_pass=1/structural_pass=1 and read as healthy forever
  // while never actually reaching Silver (vendor identification never
  // resolves downstream in extractionPipeline.ts).
  const vendorIdentifiable = Boolean(extracted.vendorNameGuess);
  if (structuralIssues.length > 0 || !vendorIdentifiable) {
    reasonCodes.push('MISSING_IDENTIFIER');
    evidence.structuralIssues = structuralIssues;
    if (!vendorIdentifiable) evidence.vendorNameGuessMissing = true;
  }

  // --- Arithmetic: sum of line amounts (blank/null amounts count as 0 — a
  // credit/payment line with no stated amount, not an error) equals the
  // statement's own stated total, within tolerance.
  if (extracted.statementTotal === null) {
    reasonCodes.push('ARITHMETIC_MISMATCH');
    evidence.arithmetic = { reason: 'no statement_total to verify against' };
  } else {
    const sum = extracted.lines.reduce((acc, l) => acc + (l.amount ?? 0), 0);
    const diff = Math.abs(sum - extracted.statementTotal);
    evidence.arithmetic = { sum, statementTotal: extracted.statementTotal, diff };
    if (diff > ARITHMETIC_TOLERANCE) {
      reasonCodes.push('ARITHMETIC_MISMATCH');
    }
  }

  const status = reasonCodes.length === 0 ? 'pass' : 'fail';
  return {
    stage: 'validation',
    status,
    reasonCodes,
    evidence,
    // S7: a failed validation triggers the retry path (or OCR_LOW_CONFIDENCE
    // once bounded), which is itself a form of required review.
    requiresReview: status === 'fail',
  };
}
