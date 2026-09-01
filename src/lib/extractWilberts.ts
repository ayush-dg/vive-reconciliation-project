import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import type { ExtractedLine, ExtractedStatement, ExtractionOutcome } from './aiProvider';

/** Session 9, Task 9.4 — Wilbert's Inc. known-vendor deterministic
 * extractor, reusing scripts/extract_wilberts.py (ported from the
 * reference implementation, see that file's own doc comment). */

const PYTHON_EXECUTABLE = process.env.PYTHON_EXECUTABLE ?? 'python';

export const WILBERTS_SIGNATURES = ["Wilbert's Inc"];
export const WILBERTS_VENDOR_SLUG = 'wilberts_inc';

type WilbertsResult = {
  vendor_name_guess: string | null;
  statement_period: string | null;
  statement_total: number | null;
  lines: { invoice_ref: string | null; ro_number: string | null; amount: number | null; date: string | null }[];
};

function runSubprocess(pdfPath: string): Promise<WilbertsResult | { error: string }> {
  return new Promise((resolve, reject) => {
    const scriptPath = path.resolve(process.cwd(), 'scripts', 'extract_wilberts.py');
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
        reject(new Error(`extract_wilberts.py produced non-JSON output: ${stdout || stderr}`));
      }
    });
  });
}

export async function extractViaWilberts(pdfBytes: Buffer): Promise<ExtractionOutcome> {
  const tmpPath = path.join(os.tmpdir(), `extract-wilberts-${process.pid}-${Date.now()}.pdf`);
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
