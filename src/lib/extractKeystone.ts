import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import type { ExtractedLine, ExtractedStatement, ExtractionOutcome } from './aiProvider';

/**
 * Session 9, Task 9.2 — Keystone Automotive Industries known-vendor
 * deterministic extractor, reusing scripts/extract_keystone.py (ported from
 * the reference implementation, see that file's own doc comment). Claude's
 * generic vision prompt scored 0% on this vendor (every line's amount came
 * back wrong sign/value) before this was wired in.
 */

const PYTHON_EXECUTABLE = process.env.PYTHON_EXECUTABLE ?? 'python';

export const KEYSTONE_SIGNATURES = ['Keystone Automotive Industries'];
export const KEYSTONE_VENDOR_SLUG = 'keystone_automotive_industries';

type KeystoneResult = {
  vendor_name_guess: string | null;
  statement_period: string | null;
  statement_total: number | null;
  lines: { invoice_ref: string | null; ro_number: string | null; amount: number | null; date: string | null }[];
};

function runSubprocess(pdfPath: string): Promise<KeystoneResult | { error: string }> {
  return new Promise((resolve, reject) => {
    const scriptPath = path.resolve(process.cwd(), 'scripts', 'extract_keystone.py');
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
        reject(new Error(`extract_keystone.py produced non-JSON output: ${stdout || stderr}`));
      }
    });
  });
}

export async function extractViaKeystone(pdfBytes: Buffer): Promise<ExtractionOutcome> {
  const tmpPath = path.join(os.tmpdir(), `extract-keystone-${process.pid}-${Date.now()}.pdf`);
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
      lineConfidence: 1.0, // real geometry-based column reconstruction, not a guess
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
