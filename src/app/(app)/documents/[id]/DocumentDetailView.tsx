'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useToast } from '@/components/ToastProvider';
import InlineLoadError from '@/components/InlineLoadError';
import type { DocumentDetailData } from '@/lib/documentDetail';

// Labels per UI_SURFACE.md Document Detail: "pdfplumber_fallback labeled plainly as 'via
// OCR fallback' for the AP user" — the other two providers get similarly plain labels
// rather than showing the raw internal provider_used string.
const PROVIDER_LABELS: Record<string, string> = {
  python_library_pdfplumber: 'Deterministic (pdfplumber)',
  claude_sonnet: 'Claude Sonnet',
  pdfplumber_fallback: 'via OCR fallback',
  // extractionMethodSummary.ts's own "unknown" bucket (a catastrophic pre-provider-
  // selection failure, Task 3.1's Finding 3) — plainly labeled like the other three,
  // not left showing the raw internal bucket key.
  unknown: 'Unknown (extraction failed before a provider was selected)',
};

function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider;
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

        <div className="panel" style={{ padding: 20, marginBottom: 20 }} data-testid="extraction-summary-strip">
          <h2 style={{ marginBottom: 12 }}>Extraction summary</h2>
          {providerEntries.length === 0 ? (
            <p style={{ color: 'var(--text-faint)' }}>No extraction attempts yet.</p>
          ) : (
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              {providerEntries.map(([provider, count]) => (
                <div key={provider} data-testid={`provider-count-${provider}`}>
                  <div style={{ fontSize: 22, fontWeight: 700 }}>{count}</div>
                  <div style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>{providerLabel(provider)}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2>Extracted lines</h2>
          </div>
          <table data-testid="statement-lines-table">
            <thead>
              <tr>
                <th>Invoice Ref</th>
                <th>Amount</th>
                <th>Confidence</th>
                <th>Provider</th>
              </tr>
            </thead>
            <tbody>
              {detail.lines.length === 0 && (
                <tr>
                  <td colSpan={4} style={{ color: 'var(--text-faint)', textAlign: 'center' }}>
                    No extracted lines yet.
                  </td>
                </tr>
              )}
              {detail.lines.map((line) => (
                <tr key={line.lineId} data-testid={`statement-line-${line.lineId}`}>
                  <td className="mono">{line.invoiceRef ?? '—'}</td>
                  <td className="mono">{line.amount.toFixed(2)}</td>
                  <td className="mono">{line.confidence !== null ? line.confidence.toFixed(2) : '—'}</td>
                  <td>{line.providerUsed ? providerLabel(line.providerUsed) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
