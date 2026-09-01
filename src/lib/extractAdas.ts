import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import type { ExtractedLine, ExtractedStatement, ExtractionOutcome } from './aiProvider';

/** Session 9, Task 9.4 — Adas Calibration Experts known-vendor
 * deterministic extractor, reusing scripts/extract_adas.py (ported from
 * the reference implementation, see that file's own doc comment). */

const PYTHON_EXECUTABLE = process.env.PYTHON_EXECUTABLE ?? 'python';

export const ADAS_SIGNATURES = ['Adas Calibration Experts'];
export const ADAS_VENDOR_SLUG = 'adas_calibration_experts';

type AdasResult = {
  vendor_name_guess: string | null;
  statement_period: string | null;
  statement_total: number | null;
  lines: { invoice_ref: string | null; ro_number: string | null; amount: number | null; date: string | null }[];
};

function runSubprocess(pdfPath: string): Promise<AdasResult | { error: string }> {
  return new Promise((resolve, reject) => {
    const scriptPath = path.resolve(process.cwd(), 'scripts', 'extract_adas.py');
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
        reject(new Error(`extract_adas.py produced non-JSON output: ${stdout || stderr}`));
      }
    });
  });
}

export async function extractViaAdas(pdfBytes: Buffer): Promise<ExtractionOutcome> {
  const tmpPath = path.join(os.tmpdir(), `extract-adas-${process.pid}-${Date.now()}.pdf`);
  await fs.writeFile(tmpPath, pdfBytes);

  try {
    const result = await runSubprocess(tmpPath);
    if ('error' in result) {
      return { rawOutput: JSON.stringify(result), extracted: null, confidence: null };
    }

    const lines: ExtractedLine[] = result.lines.map((l) => ({
      invoiceRef: l.invoice_ref,
      roNumber: l.ro_number,
      amount: l.amount,
      date: l.date,
      lineConfidence: 1.0,
    }));
    const extracted: ExtractedStatement = {
      vendorNameGuess: result.vendor_name_guess,
      statementPeriod: result.statement_period,
      statementTotal: result.statement_total,
      lines,
    };

    return { rawOutput: JSON.stringify(result), extracted, confidence: 1.0 };
  } finally {
    await fs.rm(tmpPath, { force: true });
  }
}
