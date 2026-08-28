import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import type { ExtractedLine, ExtractedStatement, ExtractionOutcome } from './aiProvider';

/**
 * Known-vendor deterministic extraction (Task 3.1's non-AI path) — a real
 * Python subprocess invoking pdfplumber (Python 3.14 + pdfplumber 0.11.10,
 * confirmed available in this environment), per Claude.md's Fixed Stack.
 * No vendor is registered with the 'deterministic' extraction_route yet
 * (data baseline = Migrated only, no seed data) — this module is exercised
 * by this session's own tests via a manually-registered test vendor, not by
 * any real onboarded vendor's statement layout.
 *
 * Line-parsing here uses the same marker format as aiProvider.ts's mock
 * ("INVOICE: X | RO: Y | AMOUNT: Z | DATE: W" per line) — a stand-in for a
 * real known-vendor layout parser, which doesn't exist because no real
 * vendor layout has been onboarded. Flagged, not silently presented as a
 * production-ready per-vendor parser.
 */

const PYTHON_EXECUTABLE = process.env.PYTHON_EXECUTABLE ?? 'python';
const LINE_PATTERN = /INVOICE:\s*(\S*)\s*\|\s*RO:\s*(\S*)\s*\|\s*AMOUNT:\s*(\S*)\s*\|\s*DATE:\s*(\S*)/g;

function parseMarkerLines(text: string): ExtractedLine[] {
  const lines: ExtractedLine[] = [];
  let match: RegExpExecArray | null;
  const pattern = new RegExp(LINE_PATTERN);
  while ((match = pattern.exec(text))) {
    const [, invoiceRef, roNumber, amountStr, date] = match;
    lines.push({
      invoiceRef: invoiceRef === '-' ? null : invoiceRef,
      roNumber: roNumber === '-' ? null : roNumber,
      amount: amountStr === '-' ? null : Number(amountStr),
      date: date === '-' ? null : date,
    });
  }
  return lines;
}

function runPdfplumberSubprocess(pdfPath: string): Promise<{ text: string } | { error: string }> {
  return new Promise((resolve, reject) => {
    const scriptPath = path.resolve(process.cwd(), 'scripts', 'pdfplumber_extract.py');
    const child = spawn(PYTHON_EXECUTABLE, [scriptPath, pdfPath]);

    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => (stdout += chunk));
    child.stderr.on('data', (chunk) => (stderr += chunk));

    child.on('error', reject); // e.g. python executable not found
    child.on('close', () => {
      try {
        resolve(JSON.parse(stdout));
      } catch {
        reject(new Error(`pdfplumber_extract.py produced non-JSON output: ${stdout || stderr}`));
      }
    });
  });
}

export async function extractViaPdfplumber(pdfBytes: Buffer): Promise<ExtractionOutcome> {
  const tmpPath = path.join(os.tmpdir(), `pdfplumber-extract-${process.pid}-${Date.now()}.pdf`);
  await fs.writeFile(tmpPath, pdfBytes);

  try {
    const result = await runPdfplumberSubprocess(tmpPath);
    if ('error' in result) {
      return { rawOutput: JSON.stringify(result), extracted: null, confidence: null };
    }

    const totalMatch = /TOTAL:\s*(\S+)/.exec(result.text);
    const vendorMatch = /VENDOR:\s*(.+)/.exec(result.text);
    const periodMatch = /PERIOD:\s*(\S+)/.exec(result.text);
    const extracted: ExtractedStatement = {
      vendorNameGuess: vendorMatch?.[1]?.trim() ?? null,
      statementPeriod: periodMatch?.[1] ?? null,
      statementTotal: totalMatch ? Number(totalMatch[1]) : null,
      lines: parseMarkerLines(result.text),
    };

    return { rawOutput: result.text, extracted, confidence: null };
  } finally {
    await fs.rm(tmpPath, { force: true });
  }
}
