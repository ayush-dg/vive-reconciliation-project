// Shared test-only helper: builds a real, pdfplumber-parseable PDF file from
// plain text, via scripts/make_test_pdf.py (PyMuPDF). Used across Session 3's
// verification scripts — not part of the application.
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const PYTHON_EXECUTABLE = process.env.PYTHON_EXECUTABLE ?? 'python';

export function makeTestPdf(text) {
  const tmpDir = os.tmpdir();
  const textPath = path.join(tmpDir, `test-pdf-text-${process.pid}-${Date.now()}-${Math.random()}.txt`);
  const pdfPath = path.join(tmpDir, `test-pdf-${process.pid}-${Date.now()}-${Math.random()}.pdf`);
  fs.writeFileSync(textPath, text, 'utf8');

  const scriptPath = path.resolve(process.cwd(), 'scripts', 'make_test_pdf.py');
  const result = spawnSync(PYTHON_EXECUTABLE, [scriptPath, pdfPath, textPath], { encoding: 'utf8' });
  fs.rmSync(textPath, { force: true });

  if (result.status !== 0) {
    throw new Error(`make_test_pdf.py failed: ${result.stderr || result.stdout}`);
  }

  const bytes = fs.readFileSync(pdfPath);
  fs.rmSync(pdfPath, { force: true });
  return bytes;
}

export function marketLine(invoiceRef, roNumber, amount, date) {
  const fmt = (v) => (v === null || v === undefined ? '-' : String(v));
  return `INVOICE: ${fmt(invoiceRef)} | RO: ${fmt(roNumber)} | AMOUNT: ${fmt(amount)} | DATE: ${fmt(date)}`;
}

export function makeStatementText({ vendor, period, total, lines }) {
  const lineTexts = lines.map((l) => marketLine(l.invoiceRef, l.roNumber, l.amount, l.date));
  const header = [`VENDOR: ${vendor}`];
  if (period) header.push(`PERIOD: ${period}`);
  header.push(`TOTAL: ${total}`);
  return [...header, ...lineTexts].join('\n');
}
