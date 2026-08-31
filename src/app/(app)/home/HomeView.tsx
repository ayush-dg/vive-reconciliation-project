'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useToast } from '@/components/ToastProvider';
import InlineLoadError from '@/components/InlineLoadError';
import type { ApiDocument } from '@/lib/documents';
import type { HomeSummaryStats } from '@/lib/homeSummary';

function formatUploadTimestamp(isoLike: string): string {
  return new Date(isoLike).toLocaleString('en-US', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  });
}

/** Home's own display mapping over status_badge (engineer-directed, 2026-08-31) — softer
 * wording than the underlying badge value, which other screens/logic (canReconcile, etc.)
 * still use unchanged: "Success" once extraction is done (not "Extracted"), and "Done"
 * once reconciliation has run AT ALL, whether or not it left open exceptions — a
 * reconciled-with-exceptions document previously showed the same alarming "Failed — see
 * Exceptions" wording an outright extraction failure does, even though the process itself
 * completed successfully; those are genuinely different situations (distinguished via
 * open_exception_count, since status_badge's 'Failed' value alone covers both). A real
 * extraction failure (exhausted retries, nothing to reconcile) still shows "Failed".
 */
function homeDisplayStatus(doc: ApiDocument): { label: string; showExceptionsLink: boolean; badgeClass: string } {
  const badge = doc.status_badge.badge;
  if (badge === 'Extracted') {
    return { label: 'Success', showExceptionsLink: false, badgeClass: 'extracted' };
  }
  if (badge === 'Reconciled') {
    return { label: 'Done', showExceptionsLink: false, badgeClass: 'reconciled' };
  }
  if (badge === 'Failed' && doc.open_exception_count > 0) {
    return { label: 'Done', showExceptionsLink: true, badgeClass: 'reconciled' };
  }
  return { label: doc.status_badge.label, showExceptionsLink: false, badgeClass: badge.toLowerCase() };
}

type HomeData = { documents: ApiDocument[]; stats: HomeSummaryStats };

export default function HomeView({
  initialDocuments,
  stats: initialStats,
}: {
  initialDocuments: ApiDocument[];
  stats: HomeSummaryStats;
}) {
  const [documents, setDocuments] = useState(initialDocuments);
  const [stats, setStats] = useState(initialStats);
  const [extractingIds, setExtractingIds] = useState<Set<string>>(new Set());
  const [reconcilingIds, setReconcilingIds] = useState<Set<string>>(new Set());
  const [loadError, setLoadError] = useState(false);
  const { showSuccess, showError } = useToast();

  // Manual refresh only (UI_SURFACE.md's resolved default — no polling infra). Never
  // throws — a failure here sets its own inline error state rather than propagating into
  // handleExtract/handleReconcile's try/catch, which would otherwise misreport a
  // successful Extract/Reconcile POST as a failed action just because the follow-up
  // refresh happened to fail.
  async function refresh() {
    try {
      const [docsRes, statsRes] = await Promise.all([fetch('/api/documents'), fetch('/api/home-summary')]);
      if (!docsRes.ok || !statsRes.ok) {
        setLoadError(true);
        return;
      }
      const data = (await docsRes.json()) as { documents: ApiDocument[] };
      setDocuments(data.documents);
      setStats((await statsRes.json()) as HomeSummaryStats);
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
  }

  async function handleExtract(documentId: string) {
    setExtractingIds((prev) => new Set(prev).add(documentId));
    try {
      const res = await fetch(`/api/documents/${documentId}/extract`, { method: 'POST' });
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
      setExtractingIds((prev) => {
        const next = new Set(prev);
        next.delete(documentId);
        return next;
      });
    }
  }

  // Task 5.1's manual matching-invocation endpoint — the same G5-locked entry point
  // Document Detail's Reconcile action also calls.
  async function handleReconcile(documentId: string) {
    setReconcilingIds((prev) => new Set(prev).add(documentId));
    try {
      const res = await fetch(`/api/documents/${documentId}/match`, { method: 'POST' });
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
      setReconcilingIds((prev) => {
        const next = new Set(prev);
        next.delete(documentId);
        return next;
      });
    }
  }

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">
          <div className="eyebrow">Home</div>
          <h1>Reports</h1>
        </div>
      </div>

      <div className="content">
        <div className="stat-cards" data-testid="home-summary-stats">
          <div className="stat-card stat-card--navy">
            <div className="stat-value" data-testid="stat-documents-processed">
              {stats.documentsProcessed}
            </div>
            <div className="stat-label">Documents processed</div>
          </div>
          <div className="stat-card stat-card--warning">
            <div className="stat-value" data-testid="stat-open-exceptions">
              {stats.openExceptions}
            </div>
            <div className="stat-label">Open exceptions</div>
          </div>
          <div className="stat-card stat-card--danger">
            <div className="stat-value" data-testid="stat-extraction-failures">
              {stats.extractionFailures}
            </div>
            <div className="stat-label">Extraction failures</div>
          </div>
          <div className="stat-card stat-card--success">
            <div className="stat-value" data-testid="stat-reconciled">
              {stats.reconciledCount}
            </div>
            <div className="stat-label">Reconciled</div>
          </div>
          <div className="stat-card stat-card--navy">
            <div className="stat-value" data-testid="stat-not-reconciled">
              {stats.notReconciledCount}
            </div>
            <div className="stat-label">Not reconciled</div>
          </div>
        </div>

        {loadError && <InlineLoadError onRetry={refresh} />}

        <div className="panel" style={{ marginTop: 20 }}>
          <div className="panel-head">
            <div>
              <h2>Most recent uploads</h2>
            </div>
          </div>
          <table data-testid="home-statements-table">
            <thead>
              <tr>
                <th>Vendor</th>
                <th>Period</th>
                <th>Status</th>
                <th>Uploaded</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {documents.length === 0 && (
                <tr key="empty">
                  <td colSpan={5} style={{ color: 'var(--text-faint)', textAlign: 'center' }} data-testid="home-empty-state">
                    No statements uploaded yet. <Link href="/upload">Upload a statement</Link>.
                  </td>
                </tr>
              )}
              {documents.map((doc) => {
                const canExtract = doc.status === 'registered';
                // 'Extracted' (not 'Processing') — extraction must have actually
                // succeeded before there's anything for Reconcile to match.
                const canReconcile = doc.status === 'processing' && doc.status_badge.badge === 'Extracted';
                const displayStatus = homeDisplayStatus(doc);
                return (
                  <tr key={doc.document_id} data-testid={`home-document-row-${doc.document_id}`}>
                    <td>
                      <Link href={`/documents/${doc.document_id}`} data-testid={`view-statement-${doc.document_id}`}>
                        {doc.vendor_slug ?? <span data-testid="vendor-identifying">Identifying…</span>}
                      </Link>
                    </td>
                    <td className="mono">{doc.statement_period ?? '—'}</td>
                    <td>
                      <span
                        className={`badge status-badge ${displayStatus.badgeClass}`}
                        data-testid={`home-status-badge-${doc.document_id}`}
                      >
                        {displayStatus.label}
                      </span>
                      {displayStatus.showExceptionsLink && doc.vendor_slug && (
                        <Link
                          href={`/exceptions?search=${encodeURIComponent(doc.vendor_slug)}`}
                          className="show-exceptions-link"
                          data-testid={`home-show-exceptions-${doc.document_id}`}
                        >
                          Show exceptions →
                        </Link>
                      )}
                    </td>
                    <td className="mono">{formatUploadTimestamp(doc.upload_timestamp)}</td>
                    <td>
                      {canExtract && (
                        <button
                          type="button"
                          className="btn btn-secondary"
                          disabled={extractingIds.has(doc.document_id)}
                          onClick={() => handleExtract(doc.document_id)}
                          data-testid={`home-extract-button-${doc.document_id}`}
                        >
                          {extractingIds.has(doc.document_id) ? 'Extracting…' : 'Extract'}
                        </button>
                      )}
                      {canReconcile && (
                        <button
                          type="button"
                          className="btn btn-secondary"
                          disabled={reconcilingIds.has(doc.document_id)}
                          onClick={() => handleReconcile(doc.document_id)}
                          data-testid={`home-reconcile-button-${doc.document_id}`}
                        >
                          {reconcilingIds.has(doc.document_id) ? 'Reconciling…' : 'Reconcile'}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
