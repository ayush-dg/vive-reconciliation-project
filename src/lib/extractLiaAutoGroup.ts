import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import type { ExtractedLine, ExtractedStatement, ExtractionOutcome } from './aiProvider';

/**
 * Session 8, Task 8.1 — the one real known-vendor deterministic extractor
 * this build wires up (Lia Auto Group), reusing scripts/extract_lia.py
 * (ported from the reference implementation, see that file's own doc
 * comment). A vendor with no registered deterministic extractor still falls
 * through to the Claude-primary path, exactly as before this task.
 */

const PYTHON_EXECUTABLE = process.env.PYTHON_EXECUTABLE ?? 'python';

/** The exact strings vendorIdentification.ts checks a document's raw text
 * against to recognize a real Lia Auto Group statement — see
 * scripts/extract_lia.py's own VENDOR_SIGNATURE (kept in sync manually;
 * there's no shared source between a Python list and this TS array). */
export const LIA_AUTO_GROUP_SIGNATURES = ['LIA AUTO GROUP', 'Lia Group Payables'];
export const LIA_AUTO_GROUP_VENDOR_SLUG = 'lia_auto_group';

type LiaResult = {
  vendor_name_guess: string | null;
  statement_period: string | null;
  statement_total: number | null;
  lines: { invoice_ref: string | null; ro_number: string | null; amount: number | null; date: string | null }[];
};

function runSubprocess(pdfPath: string): Promise<LiaResult | { error: string }> {
  return new Promise((resolve, reject) => {
    const scriptPath = path.resolve(process.cwd(), 'scripts', 'extract_lia.py');
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
        reject(new Error(`extract_lia.py produced non-JSON output: ${stdout || stderr}`));
      }
    });
  });
}

export async function extractViaLiaAutoGroup(pdfBytes: Buffer): Promise<ExtractionOutcome> {
  const tmpPath = path.join(os.tmpdir(), `extract-lia-${process.pid}-${Date.now()}.pdf`);
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
      lineConfidence: 1.0, // real geometry-based table reconstruction, not a guess
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
