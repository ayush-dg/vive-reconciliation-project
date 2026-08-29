import Link from 'next/link';
import type { ExceptionDetailData } from '@/lib/exceptionDetail';

const CATEGORY_LABELS: Record<string, string> = {
  amount_mismatch: 'Amount Mismatch',
  not_posted: 'Not Posted',
};

// No approve/dispute actions on this screen — correctly absent per ARCHITECTURE.md D-C.
// The only action is "Back to list". No client-side state is needed (no fetch/refresh,
// the amount-mismatch section is a native <details> element), so this stays a plain
// server component rather than 'use client'.
export default function ExceptionDetailView({ detail }: { detail: ExceptionDetailData }) {
  return (
    <>
      <div className="topbar">
        <div className="topbar-title">
          <div className="eyebrow">Exception</div>
          <h1 data-testid="exception-detail-vendor">{detail.statementLine.vendorSlug ?? 'Unknown vendor'}</h1>
        </div>
        <Link href="/exceptions" className="btn btn-secondary" data-testid="back-to-exceptions">
          Back to list
        </Link>
      </div>

      <div className="content">
        <div className="panel" style={{ padding: 20, marginBottom: 20 }}>
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'center' }}>
            <span
              className={`badge badge-${detail.category === 'amount_mismatch' ? 'warning' : 'danger'}`}
              data-testid="exception-detail-category"
            >
              {CATEGORY_LABELS[detail.category] ?? detail.category}
            </span>
            <span className="mono">Invoice: {detail.statementLine.invoiceRef ?? '—'}</span>
            <span className="mono">Amount: {detail.statementLine.amount.toFixed(2)}</span>
            <span className="mono">Period: {detail.statementLine.statementPeriod ?? '—'}</span>
          </div>
        </div>

        <div className="panel" style={{ padding: 20, marginBottom: 20 }} data-testid="ccc-evidence-panel">
          <h2 style={{ marginBottom: 10 }}>Related — CCC corroborating evidence</h2>
          {detail.cccCorroboration ? (
            <p className="mono" data-testid="ccc-evidence-content">
              RO {detail.cccCorroboration.roNumber} — {detail.cccCorroboration.amount.toFixed(2)}
            </p>
          ) : (
            <p style={{ color: 'var(--text-faint)' }} data-testid="ccc-evidence-empty">
              No CCC confirmation available
            </p>
          )}
        </div>

        {detail.amountMismatch && (
          <details className="evidence-drilldown" data-testid="amount-mismatch-drilldown">
            <summary>Amount mismatch — statement vs. NetSuite value</summary>
            <div style={{ marginTop: 10 }} className="mono">
              <div data-testid="amount-mismatch-statement-value">Statement: {detail.amountMismatch.statementAmount.toFixed(2)}</div>
              <div data-testid="amount-mismatch-netsuite-value">NetSuite: {detail.amountMismatch.netsuiteAmount.toFixed(2)}</div>
            </div>
            {detail.referenceExtractedAt && (
              <div className="as-of" data-testid="amount-mismatch-as-of">
                As of {new Date(detail.referenceExtractedAt).toLocaleString('en-US')} — not a live re-query
              </div>
            )}
          </details>
        )}
      </div>
    </>
  );
}
