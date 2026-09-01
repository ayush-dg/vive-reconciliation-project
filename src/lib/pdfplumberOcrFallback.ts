import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import type { ExtractedLine, ExtractedStatement, ExtractionOutcome } from './aiProvider';

/**
 * Session 8, Task 8.3 — the actual OCR/pdfplumber fallback tier. Only ever
 * invoked by extractionPipeline.ts's retry loop after a genuine Claude
 * failure (Task 8.2's routing) — never tried first, never a substitute for
 * the known-vendor deterministic path (pdfplumberExtractor.ts, a different
 * script/module). Same subprocess I/O shape as pdfplumberExtractor.ts:
 * spawn a Python script against a temp PDF file, parse one JSON object off
 * stdout.
 */

const PYTHON_EXECUTABLE = process.env.PYTHON_EXECUTABLE ?? 'python';

type FallbackResult = {
  vendor_name_guess: string | null;
  statement_period: string | null;
  statement_total: number | null;
  lines: { invoice_ref: string | null; ro_number: string | null; amount: number | null; date: string | null }[];
  warnings: string[];
  ocr_pages_used: number[];
  ocr_available: boolean;
};

function runSubprocess(pdfPath: string): Promise<FallbackResult | { error: string }> {
  return new Promise((resolve, reject) => {
    const scriptPath = path.resolve(process.cwd(), 'scripts', 'pdfplumber_ocr_fallback.py');
    const child = spawn(PYTHON_EXECUTABLE, [scriptPath, pdfPath]);

    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => (stdout += chunk));
    child.stderr.on('data', (chunk) => (stderr += chunk));

    child.on('error', reject);
    child.on('close', () => {
      try {
        resolve(JSON.parse(stdout));
      } catch {
        reject(new Error(`pdfplumber_ocr_fallback.py produced non-JSON output: ${stdout || stderr}`));
      }
    });
  });
}

export async function extractViaPdfplumberOcrFallback(pdfBytes: Buffer): Promise<ExtractionOutcome> {
  const tmpPath = path.join(os.tmpdir(), `pdfplumber-ocr-fallback-${process.pid}-${Date.now()}.pdf`);
  await fs.writeFile(tmpPath, pdfBytes);

  try {
    const result = await runSubprocess(tmpPath);
    if ('error' in result) {
      return { rawOutput: JSON.stringify(result), extracted: null, confidence: null };
    }

    // Diagnostic only (G2/IC-2 — never a gate): lower when OCR-derived rows
    // are present, since column boundaries there are inferred from flat OCR
    // text rather than real table geometry. Applied uniformly to every line
    // in this batch — the Python side doesn't track which specific page (OCR
    // vs. real table) produced which line, only whether OCR was used at all.
    const lineConfidence = result.ocr_pages_used.length > 0 ? 0.5 : 0.65;

    const lines: ExtractedLine[] = result.lines.map((l) => ({
      invoiceRef: l.invoice_ref,
      roNumber: l.ro_number,
      amount: l.amount,
      date: l.date,
      lineConfidence,
    }));
    const extracted: ExtractedStatement = {
      vendorNameGuess: result.vendor_name_guess,
      statementPeriod: result.statement_period,
      statementTotal: result.statement_total,
      lines,
    };

    // No lines at all is a real, honest failure for this last-resort path —
    // never silently promote an empty extraction as if it succeeded.
    if (lines.length === 0) {
      return { rawOutput: JSON.stringify(result), extracted: null, confidence: null };
    }

    return { rawOutput: JSON.stringify(result), extracted, confidence: lineConfidence };
  } finally {
    await fs.rm(tmpPath, { force: true });
  }
}
