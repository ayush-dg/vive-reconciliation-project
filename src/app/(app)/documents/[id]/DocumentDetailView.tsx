'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useToast } from '@/components/ToastProvider';
import InlineLoadError from '@/components/InlineLoadError';
import type { DocumentDetailData } from '@/lib/documentDetail';

// Short, sentence-friendly labels for "extracted using X" (folded into the
// reconciliation-progress line, not shown as its own panel — engineer-directed
// 2026-09-04: the standalone per-provider stat panel was removed as unwanted
// visual noise once this sentence already carries the same information).
// pdfplumber_fallback's label deliberately drops "via" (unlike the old standalone
// panel's "via OCR fallback") since the surrounding sentence already supplies it.
const PROVIDER_LABELS: Record<string, string> = {
  python_library_pdfplumber: 'pdfplumber',
  claude_sonnet: 'Claude Sonnet',
  pdfplumber_fallback: 'OCR fallback',
  // extractionMethodSummary.ts's own "unknown" bucket (a catastrophic pre-provider-
  // selection failure, Task 3.1's Finding 3) — plainly labeled like the other three,
  // not left showing the raw internal bucket key.
  unknown: 'an unknown method (extraction failed before a provider was selected)',
};

function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider;
}

// Joins 1+ providers into "Claude Sonnet" / "pdfplumber" / "Claude Sonnet and OCR
// fallback" / "A, B and C". Empty when no attempt has been made yet — a genuinely
// FAILED extraction still has a recorded provider (attempted, just unsuccessful) even
// though it produced zero lines, so callers must check this independently of line
// count, not assume "no lines" means "no provider to name" (they're different facts).
function extractionMethodNames(providerEntries: [string, number][]): string {
  if (providerEntries.length === 0) return '';
  const labels = providerEntries.map(([provider]) => providerLabel(provider));
  if (labels.length === 1) return labels[0];
  return `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`;
}

export default function DocumentDetailView({ detail: initialDetail }: { detail: DocumentDetailData }) {
  const [detail, setDetail] = useState(initialDetail);
  const [extracting, setExtracting] = useState(false);
  const [reconciling, setReconciling] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const { showSuccess, showError } = useToast();

  // Never throws — a failure here sets its own inline error state rather than
  // propagating into handleExtract/handleReconcile's try/catch, which would otherwise
  // misreport a successful Extract/Reconcile POST as a failed action just because the
  // follow-up refresh happened to fail.
  async function refresh() {
    try {
      const res = await fetch(`/api/documents/${detail.documentId}/detail`);
      if (!res.ok) {
        setLoadError(true);
        return;
      }
      setDetail((await res.json()) as DocumentDetailData);
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
  }

  // Same D-I/G5 discipline as Upload's Extract action (Task 2.4) — this is just a second
  // entry point to the identical endpoint, not a separate implementation.
  async function handleExtract() {
    setExtracting(true);
    try {
      const res = await fetch(`/api/documents/${detail.documentId}/extract`, { method: 'POST' });
      if (res.status === 409) {
        showError('Extraction already in progress for this document.');
        await refresh();
        return;
      }
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { error?: string };
        showError(data.error ?? 'Failed to start extraction.');
        return;
      }
      showSuccess('Extraction started.');
      await refresh();
    } catch {
      showError('Failed to start extraction — check your connection and try again.');
    } finally {
      setExtracting(false);
    }
  }

  // Same G5 discipline as Home's Reconcile action (Task 5.1's manual invocation endpoint).
  async function handleReconcile() {
    setReconciling(true);
    try {
      const res = await fetch(`/api/documents/${detail.documentId}/match`, { method: 'POST' });
      if (res.status === 409) {
        showError('Matching already in progress for this document.');
        await refresh();
        return;
      }
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { error?: string };
        showError(data.error ?? 'Failed to start matching.');
        return;
      }
      showSuccess('Reconciliation started.');
      await refresh();
    } catch {
      showError('Failed to start matching — check your connection and try again.');
    } finally {
      setReconciling(false);
    }
  }

  const canExtract = detail.status === 'registered';
  // 'Extracted' (not 'Processing') — extraction must have actually succeeded
  // before there's anything for Reconcile to match.
  const canReconcile = detail.status === 'processing' && detail.statusBadge.badge === 'Extracted';
  const providerEntries = Object.entries(detail.extractionMethodSummary);

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">
          <div className="eyebrow">Document</div>
          <h1 data-testid="document-detail-vendor">{detail.vendorSlug ?? 'Identifying…'}</h1>
        </div>
        <Link href="/home" className="btn btn-secondary" data-testid="back-to-home">
          Back to Home
        </Link>
      </div>

      <div className="content">
        {loadError && <InlineLoadError onRetry={refresh} />}

        <div className="panel" style={{ padding: 20, marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
            <span
              className={`badge status-badge ${detail.statusBadge.badge.toLowerCase()}`}
              data-testid="document-detail-status-badge"
            >
              {detail.statusBadge.label}
            </span>
            <span className="mono">{detail.statementPeriod ?? 'Period not yet known'}</span>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 10 }}>
              {canExtract && (
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={extracting}
                  onClick={handleExtract}
                  data-testid="document-detail-extract-button"
                >
                  {extracting ? 'Extracting…' : 'Extract'}
                </button>
              )}
              {canReconcile && (
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={reconciling}
                  onClick={handleReconcile}
                  data-testid="document-detail-reconcile-button"
                >
                  {reconciling ? 'Reconciling…' : 'Reconcile'}
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <div>
              <h2>Extracted lines ({detail.lines.length} total)</h2>
              <div className="sub" data-testid="reconciliation-progress">
                {(() => {
                  const { totalLines, matchedLines, exceptionLines } = detail.reconciliation;
                  const processed = matchedLines + exceptionLines;
                  const methodNames = extractionMethodNames(providerEntries);
                  if (totalLines === 0) {
                    // A genuinely FAILED extraction (e.g. validation failed, zero Silver
                    // rows produced) still has a recorded provider — worth surfacing here,
                    // not just silently "no lines" with no clue what was even attempted.
                    return methodNames ? `No lines extracted yet — attempted using ${methodNames}.` : 'No lines extracted yet.';
                  }
                  if (processed === 0) {
                    return methodNames ? `Reconciliation not started yet — extracted using ${methodNames}.` : 'Reconciliation not started yet.';
                  }
                  // matchingPipeline.ts commits a document's matching results atomically
                  // (all lines at once) — processed is always either 0 or totalLines,
                  // never a partial figure from a still-in-progress run.
                  const base = `Reconciliation complete — ${matchedLines} matched, ${exceptionLines} exception${exceptionLines === 1 ? '' : 's'}`;
                  return methodNames ? `${base}, extracted using ${methodNames}.` : `${base}.`;
                })()}
              </div>
            </div>
          </div>
          <table data-testid="statement-lines-table">
            <thead>
              <tr>
                <th>Invoice Ref</th>
                <th>Amount</th>
              </tr>
            </thead>
            <tbody>
              {detail.lines.length === 0 && (
                <tr>
                  <td colSpan={2} style={{ color: 'var(--text-faint)', textAlign: 'center' }}>
                    No extracted lines yet.
                  </td>
                </tr>
              )}
              {detail.lines.map((line) => (
                <tr key={line.lineId} data-testid={`statement-line-${line.lineId}`}>
                  <td className="mono">{line.invoiceRef ?? '—'}</td>
                  <td className="mono">{line.amount.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
